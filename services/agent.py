"""LLM orchestrator: tool-calling loop + deterministic verification."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from data import config

from .conversation import ConversationStore
from .answer_contract import Draft, SYNTHESIS_CONTRACT, parse_draft, verify_metrics
from .guardrails import has_partial_refusal
from .database import Database
from .guardrails import (
    EvidenceIndex,
    VerificationResult,
    correction_prompt,
    format_evidence_footer,
    has_evidence_line,
    is_no_answer,
    no_answer,
    verify_answer,
)
from .language import UZ
from .llm import LLMClient, LLMError
from .prompts import build_system_prompt
from .tools import TOOLS, ToolRunner

logger = logging.getLogger(__name__)

KNOWN_TABLES = {"deals_enriched", "deals", "contracts", "participants", "brokers", "usd_rates"}
TABLE_RE = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)

DATASET_FACTS = f"""
UZEX Spot registry — fictional hackathon dataset.
Total deals: {config.TOTAL_DEALS}. Deal years: 2022, 2023, 2024, 2025, 2026.
Deal dates: {config.DEALS_MIN_DATE} through {config.DEALS_MAX_DATE}.
Contracts: 6616. Participants: 14392. Brokers: 120. USD rates: 1765 rows,
{config.RATES_MIN_DATE} through {config.RATES_MAX_DATE}.
Currency codes: UZS, USD.
Deal states (8): Новый, Не подписан, Заключен, Ждёт оплату, Оплачен, Исполнен,
Исполнен(Частично), Аннулирован(Не оплачен).
Tables: deals_enriched, deals, contracts, participants, brokers, usd_rates.
"""


class AgentError(RuntimeError):
    """A service/verification failure, never evidence of missing registry data."""

    def __init__(self, message: str, outcome: str = "execution_failed"):
        super().__init__(message)
        self.outcome = outcome


@dataclass(slots=True)
class AgentAnswer:
    text: str
    language: str
    sql_queries: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    tool_calls: int = 0
    rows: int = 0
    guardrail_ok: bool = True
    regenerated: bool = False
    no_answer: bool = False
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    latency: float = 0.0
    outcome: str = "answered"
    coverage: list[dict[str, str]] = field(default_factory=list)
    analysis: dict[str, Any] | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    cache_hits: int = 0
    cache_misses: int = 0
    query_count: int = 0


@dataclass(slots=True)
class RunState:
    messages: list[dict[str, Any]]
    evidence: EvidenceIndex
    sql_queries: list[str] = field(default_factory=list)
    tables: set[str] = field(default_factory=set)
    tool_calls: int = 0
    successful_tools: int = 0
    database_errors: int = 0
    rows: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    last_text: str = ""
    model: str = ""
    forced_tool_retry: bool = False
    empty_retry: bool = False
    trace: list[dict[str, Any]] = field(default_factory=list)
    internal_queries: int = 0
    cache_hits: int = 0
    cache_misses: int = 0


class Agent:
    def __init__(
        self,
        database: Database,
        llm: LLMClient,
        tools: ToolRunner | None = None,
        max_tool_rounds: int = config.LLM_MAX_TOOL_ROUNDS,
    ) -> None:
        self.database = database
        self.llm = llm
        self.tools = tools or ToolRunner(database)
        self.max_tool_rounds = max(2, max_tool_rounds)

    async def answer(
        self,
        question: str,
        language: str,
        history: list[dict[str, str]] | None = None,
    ) -> AgentAnswer:
        started = time.perf_counter()
        if not self.database.available:
            raise AgentError("database is not available")

        state = RunState(
            messages=[
                {"role": "system", "content": build_system_prompt(language) + "\n" + SYNTHESIS_CONTRACT},
                *(history or []),
                {"role": "user", "content": question},
            ],
            evidence=EvidenceIndex(),
        )
        state.evidence.add(DATASET_FACTS)
        state.evidence.add_request(question)

        def record_failure(error: Exception) -> None:
            error.trace = state.trace
            error.evidence = state.evidence.results
            error.draft = state.last_text
            error.sql_queries = state.sql_queries
            error.usage = state.usage
            error.latency = time.perf_counter() - started
            error.tool_calls = state.tool_calls
            error.cache_hits, error.cache_misses = state.cache_hits, state.cache_misses

        def failure(message: str, outcome: str = "execution_failed") -> AgentError:
            error = AgentError(message, outcome)
            record_failure(error)
            return error

        try:
            state = await self._run_loop(state, self.max_tool_rounds)
        except (AgentError, LLMError) as exc:
            record_failure(exc)
            raise
        if not state.last_text.strip():
            raise failure("the language model returned an empty answer")
        if state.tool_calls and state.database_errors == state.tool_calls:
            raise failure("all database queries failed")

        envelope, verification = self._verify_draft(state, language)
        draft = envelope.text
        regenerated = False

        if verification.needs_regeneration and not is_no_answer(draft):
            logger.warning(
                "regenerating answer; unsupported numbers=%s names=%s",
                verification.unsupported_numbers,
                verification.unsupported_names,
            )
            regenerated = True
            state.messages.append({"role": "assistant", "content": state.last_text})
            state.messages.append(
                {
                    "role": "user",
                    "content": correction_prompt(
                        language,
                        verification.unsupported_numbers,
                        verification.unsupported_names,
                    ),
                }
            )
            state.last_text = ""
            state.empty_retry = False
            try:
                state = await self._run_loop(state, max(2, self.max_tool_rounds // 2))
            except (AgentError, LLMError) as exc:
                record_failure(exc)
                raise
            if state.last_text.strip():
                envelope, verification = self._verify_draft(state, language)
                draft = envelope.text
            else:
                raise failure("empty verification repair", "verification_failed")

        if verification.needs_regeneration or verification.empty:
            logger.warning(
                "guardrail rejected answer; unsupported numbers=%s names=%s",
                verification.unsupported_numbers,
                verification.unsupported_names,
            )
            raise failure("answer could not be verified against query results", "verification_failed")

        if regenerated and is_no_answer(draft) and state.rows:
            raise failure("verification repair discarded available data", "verification_failed")
        if state.tool_calls and not state.successful_tools:
            raise failure("all tool calls failed")

        final_text = draft.strip()
        if not is_no_answer(final_text) and not has_evidence_line(final_text):
            footer = format_evidence_footer(
                language,
                sorted(state.tables),
                len(state.sql_queries) + state.internal_queries,
                state.rows,
            )
            final_text = f"{final_text}\n\n{footer}"

        return AgentAnswer(
            text=final_text,
            language=language,
            sql_queries=state.sql_queries,
            tables=sorted(state.tables),
            tool_calls=state.tool_calls,
            rows=state.rows,
            guardrail_ok=verification.ok,
            regenerated=regenerated,
            no_answer=is_no_answer(final_text),
            model=state.model,
            usage=state.usage,
            latency=time.perf_counter() - started,
            outcome=(("unsupported_request" if envelope.outcome == "unsupported_request" else "no_data") if is_no_answer(final_text) else "partial"
                     if has_partial_refusal(final_text) or any(
                         c["status"] != "answered" for c in envelope.coverage) else "answered"),
            coverage=envelope.coverage,
            analysis=envelope.analysis.to_dict() if envelope.analysis else None,
            metrics=envelope.metrics,
            evidence=state.evidence.results,
            trace=state.trace,
            cache_hits=state.cache_hits,
            cache_misses=state.cache_misses,
            query_count=len(state.sql_queries) + state.internal_queries,
        )

    def _verify_draft(self, state: RunState, language: str) -> tuple[Draft, VerificationResult]:
        try:
            draft = parse_draft(state.last_text)
        except ValueError as exc:
            return Draft(state.last_text), VerificationResult(ok=False,
                unsupported_numbers=[f"invalid response format: {exc}"])
        verification = verify_answer(draft.text, state.evidence, language)
        if not verify_metrics(draft.metrics, state.evidence.results):
            verification.ok = False
            verification.unsupported_numbers.append("invalid metric source reference")
        return draft, verification

    async def _synthesize(self, state: RunState, reason: str = "query_budget") -> RunState:
        state.messages.append({"role": "user", "content": (
            f"Finalization phase ({reason}). Return the complete final JSON response without tools. "
            "Use available successful evidence; cover each requested output and mark unresolved "
            "parts explicitly. Do not claim the registry lacks data because the budget expired."
        )})
        response = await self.llm.chat(state.messages, tools=None, max_tokens=config.LLM_FINAL_MAX_TOKENS)
        _accumulate_usage(state.usage, response.usage)
        state.model = response.model or state.model
        state.trace.append({"phase": "synthesis", "finish_reason": response.finish_reason,
                            "unexpected_tools": bool(response.tool_calls)})
        if response.tool_calls or response.finish_reason == "length":
            raise AgentError("reserved synthesis did not complete")
        state.last_text = (response.content or "").strip()
        return state

    # ------------------------------------------------------------------
    # Tool loop
    # ------------------------------------------------------------------
    async def _run_loop(self, state: RunState, max_rounds: int) -> RunState:
        for round_index in range(max_rounds):
            response = await self.llm.chat(state.messages, tools=TOOLS)
            state.model = response.model or state.model
            _accumulate_usage(state.usage, response.usage)

            state.trace.append({"phase": "query", "round": round_index + 1,
                                "budget_remaining": max_rounds - round_index - 1,
                                "finish_reason": response.finish_reason})
            if response.tool_calls:
                state.messages.append(response.message)
                for call in response.tool_calls:
                    function = call.get("function") or {}
                    name = str(function.get("name") or "")
                    raw_arguments = function.get("arguments") or "{}"
                    state.tool_calls += 1
                    try:
                        arguments = json.loads(raw_arguments)
                        if not isinstance(arguments, dict):
                            raise ValueError("arguments must be a JSON object")
                    except (TypeError, ValueError) as exc:
                        result = json.dumps(
                            {
                                "ok": False,
                                "tool": name,
                                "error": f"invalid tool arguments: {exc}",
                            },
                            ensure_ascii=False,
                        )
                        arguments = {}
                    else:
                        result = await self.tools.run(name, arguments)

                    if name == "run_sql" and isinstance(arguments, dict):
                        query = arguments.get("query")
                        if isinstance(query, str) and query.strip():
                            state.sql_queries.append(query.strip())
                            state.tables.update(_extract_tables(query))
                            # Date filters are added to the evidence only after
                            # the query succeeds (see below).

                    try:
                        payload = json.loads(result)
                        payload["evidence_id"] = f"e{len(state.trace) + 1}"
                        result = json.dumps(payload, ensure_ascii=False)
                    except (ValueError, TypeError):
                        payload = {}
                    state.trace.append({"phase": "tool", "name": name,
                                        "evidence_id": payload.get("evidence_id"),
                                        "ok": bool(payload.get("ok")), "cache": payload.get("cache"),
                                        "error": payload.get("error")})
                    state.cache_hits += payload.get("cache") == "hit"
                    state.cache_misses += payload.get("cache") == "miss"
                    recognized = _collect_result_stats(state, name, result)
                    if recognized:
                        # Failed queries must not make their numbers/names
                        # acceptable in the final answer.
                        stored_payload = dict(payload)
                        if name == "run_sql" and isinstance(arguments.get("query"), str):
                            stored_payload["query"] = arguments["query"]
                        state.evidence.add_result(stored_payload)
                        if name in {"region_audit", "mass_ranking"}:
                            for boundary in payload.get("scope", {}).values():
                                if isinstance(boundary, str):
                                    state.evidence.add(boundary, numbers=False, names=False)
                        if name == "run_sql" and isinstance(arguments, dict):
                            query = arguments.get("query")
                            if isinstance(query, str) and query.strip():
                                state.evidence.add_query_scope(query)
                    state.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": result,
                        }
                    )
                continue

            if response.finish_reason == "length":
                # A truncated JSON draft is not an analytical failure and needs
                # no new SQL. Use the reserved, larger final output budget.
                return await self._synthesize(state, "output_truncated")
            text = (response.content or "").strip()
            if not text:
                if state.empty_retry:
                    break
                state.empty_retry = True
                state.messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your response was empty. Either call a tool to obtain the data "
                            "or return the final JSON response with supported parts and explicit limitations."
                        ),
                    }
                )
                continue

            if state.tool_calls == 0 and not is_no_answer(text) and not state.forced_tool_retry:
                state.forced_tool_retry = True
                state.messages.append({"role": "assistant", "content": text})
                state.messages.append(
                    {
                        "role": "user",
                        "content": (
                            "You answered without using any tool. You must verify the answer "
                            "with the available tools (SQL, product/company search, USD rate). "
                            "Call the necessary tools now, then answer again. If the data has "
                            "no answer, reply with the required no-answer sentence."
                        ),
                    }
                )
                continue

            state.last_text = text
            return state

        return await self._synthesize(state)


def _accumulate_usage(target: dict[str, int], usage: dict[str, Any]) -> None:
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        try:
            target[key] = target.get(key, 0) + int(usage.get(key, 0) or 0)
        except (TypeError, ValueError):
            continue


def _collect_result_stats(state: RunState, name: str, result: str) -> bool:
    """Record tool stats; return True when the tool result is trustworthy evidence."""

    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    if not payload.get("ok"):
        error = str(payload.get("error") or "")
        if "database error" in error.lower():
            state.database_errors += 1
        return False

    state.successful_tools += 1
    if name in {"run_sql", "region_audit", "registry_audit", "mass_ranking"}:
        if name != "run_sql":
            state.internal_queries += 1
        if name == "region_audit":
            state.tables.update({"deals", "contracts", "participants"})
        elif name == "registry_audit":
            state.tables.update(KNOWN_TABLES - {"deals_enriched"})
        elif name == "mass_ranking":
            state.tables.add("deals_enriched")
        try:
            state.rows += int(payload.get("row_count") or 0)
        except (TypeError, ValueError):
            pass
    elif name in {"search_products", "search_company"}:
        matches = payload.get("matches")
        if isinstance(matches, list):
            state.rows += len(matches)
        if name == "search_products":
            state.tables.update({"contracts", "deals"})
        else:
            state.tables.update({"participants", "brokers"})
    elif name == "usd_rate":
        state.tables.add("usd_rates")
        if payload.get("found"):
            state.rows += 1
    return True


def _extract_tables(query: str) -> set[str]:
    tables: set[str] = set()
    for match in TABLE_RE.finditer(query):
        table = match.group(1).lower()
        if table in KNOWN_TABLES:
            tables.add(table)
    return tables


def trim_history(history: list[dict[str, str]], max_messages: int = 8) -> list[dict[str, str]]:
    """Utility used by tests and callers that do not use ConversationStore."""

    return history[-max_messages:]


def make_history(store: ConversationStore, chat_id: int) -> list[dict[str, str]]:
    return trim_history(store.history(chat_id), config.MAX_HISTORY_TURNS)
