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
from .llm import LLMClient
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
Deal states: Новый, Не подписан, Заключен, Ждёт оплату, Оплачен, Исполнен,
Исполнен(Частично), Аннулирован(Не оплачен).
Tables: deals_enriched, deals, contracts, participants, brokers, usd_rates.
"""


class AgentError(RuntimeError):
    """The agent could not answer because of a service problem."""


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
                {"role": "system", "content": build_system_prompt(language)},
                *(history or []),
                {"role": "user", "content": question},
            ],
            evidence=EvidenceIndex(),
        )
        state.evidence.add(DATASET_FACTS)

        state = await self._run_loop(state, self.max_tool_rounds)
        if not state.last_text.strip():
            raise AgentError("the language model returned an empty answer")
        if state.tool_calls and state.database_errors == state.tool_calls:
            raise AgentError("all database queries failed")

        draft = state.last_text.strip()
        verification = verify_answer(draft, state.evidence, language)
        regenerated = False

        if verification.needs_regeneration and not is_no_answer(draft):
            regenerated = True
            state.messages.append({"role": "assistant", "content": draft})
            state.messages.append(
                {
                    "role": "system",
                    "content": correction_prompt(
                        language,
                        verification.unsupported_numbers,
                        verification.unsupported_names,
                    ),
                }
            )
            state.last_text = ""
            state.empty_retry = False
            state = await self._run_loop(state, max(2, self.max_tool_rounds // 2))
            if state.last_text.strip():
                draft = state.last_text.strip()
            verification = verify_answer(draft, state.evidence, language)

        if verification.needs_regeneration or verification.empty:
            logger.warning(
                "guardrail rejected answer; unsupported numbers=%s names=%s",
                verification.unsupported_numbers,
                verification.unsupported_names,
            )
            draft = no_answer(language)
            verification = VerificationResult(ok=True, no_answer=True)

        final_text = draft.strip()
        if not is_no_answer(final_text) and not has_evidence_line(final_text):
            footer = format_evidence_footer(
                language,
                sorted(state.tables),
                len(state.sql_queries),
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
        )

    # ------------------------------------------------------------------
    # Tool loop
    # ------------------------------------------------------------------
    async def _run_loop(self, state: RunState, max_rounds: int) -> RunState:
        for _ in range(max_rounds):
            response = await self.llm.chat(state.messages, tools=TOOLS)
            state.model = response.model or state.model
            _accumulate_usage(state.usage, response.usage)

            if response.tool_calls:
                state.messages.append(response.message)
                for call in response.tool_calls:
                    function = call.get("function") or {}
                    name = str(function.get("name") or "")
                    raw_arguments = function.get("arguments") or "{}"
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
                        state.tool_calls += 1
                        result = await self.tools.run(name, arguments)

                    if name == "run_sql" and isinstance(arguments, dict):
                        query = arguments.get("query")
                        if isinstance(query, str) and query.strip():
                            state.sql_queries.append(query.strip())
                            state.tables.update(_extract_tables(query))
                            # Dates in filters are legitimate context; numeric
                            # literals are not treated as evidence.
                            state.evidence.add(query, numbers=False, dates=True, names=False)

                    state.evidence.add(result)
                    _collect_result_stats(state, name, result)
                    state.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": result,
                        }
                    )
                continue

            text = (response.content or "").strip()
            if not text:
                if state.empty_retry:
                    break
                state.empty_retry = True
                state.messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Your response was empty. Either call a tool to obtain the data "
                            "or reply with the required no-answer sentence."
                        ),
                    }
                )
                continue

            if state.tool_calls == 0 and not is_no_answer(text) and not state.forced_tool_retry:
                state.forced_tool_retry = True
                state.messages.append(
                    {
                        "role": "system",
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

        return state


def _accumulate_usage(target: dict[str, int], usage: dict[str, Any]) -> None:
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        try:
            target[key] = target.get(key, 0) + int(usage.get(key, 0) or 0)
        except (TypeError, ValueError):
            continue


def _collect_result_stats(state: RunState, name: str, result: str) -> None:
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        return
    if not isinstance(payload, dict):
        return
    if payload.get("ok"):
        state.successful_tools += 1
        if name == "run_sql":
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
    else:
        error = str(payload.get("error") or "")
        if "database error" in error.lower():
            state.database_errors += 1


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
