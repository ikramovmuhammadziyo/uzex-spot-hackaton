"""Diagnose the two failing cases: capture the full tool/LLM trail and the guardrail verdict."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from data import config
from services.agent import Agent
from services.database import Database
from services.guardrails import verify_answer
from services.llm import LLMClient
from services.tools import ToolRunner
from qa.run_eval import CASES

trail: list[str] = []


class TracedLLM(LLMClient):
    async def chat(self, messages, tools=None, **kw):
        r = await super().chat(messages, tools, **kw)
        names = [c.get("function", {}).get("name") for c in (r.tool_calls or [])]
        trail.append(
            f"LLM -> content={len(r.content or '')} chars, tools={names}, finish={r.finish_reason}, "
            f"msgs={len(messages)}"
        )
        if r.content:
            trail.append(f"     text: {(r.content or '')[:300]}")
        return r


class TracedTools(ToolRunner):
    async def run(self, name, arguments):
        result = await super().run(name, arguments)
        try:
            payload = json.loads(result)
            ok = payload.get("ok")
            err = payload.get("error")
            n = payload.get("row_count")
        except Exception:  # noqa: BLE001
            ok, err, n = None, None, None
        trail.append(f"TOOL {name} ok={ok} rows={n} err={err} len={len(result)}")
        if name == "run_sql":
            trail.append(f"     sql: {str(arguments.get('query'))[:200]}")
        if ok and n is not None:
            trail.append(f"     result head: {result[:300]}")
        return result


class TracedAgent(Agent):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.state = None

    async def _run_loop(self, state, max_rounds):
        self.state = state
        return await super()._run_loop(state, max_rounds)


async def main(case_id: str) -> int:
    db = Database(config.DB_PATH)
    db.connect()
    case = next(c for c in CASES if c["id"] == case_id)
    agent = TracedAgent(db, TracedLLM(), TracedTools(db))

    print(f"=== CASE {case_id}: {case['title']}")
    text, err = "", None
    try:
        answer = await agent.answer(case["question"], "ru")
        text = answer.text
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"

    print("\n".join(trail))
    print(f"\nerror: {err}")
    print(f"final text ({len(text)} chars):\n{text}")

    st = agent.state
    if st is not None:
        print(f"\nstate: messages={len(st.messages)}, tool_calls={st.tool_calls}, "
              f"successful={st.successful_tools}, db_errors={st.database_errors}, rows={st.rows}")
        print("last 3 messages:")
        for m in st.messages[-3:]:
            role = m.get("role")
            content = str(m.get("content") or "")[:400]
            print(f"  [{role}] {content}")
        if text:
            v = verify_answer(text, st.evidence, "ru")
            print(f"\nverify: ok={v.ok} unsupported_numbers={v.unsupported_numbers} "
                  f"unsupported_names={v.unsupported_names} no_answer={v.no_answer}")
            evidence = getattr(st.evidence, "text", None) or getattr(st.evidence, "_text", None)
            if evidence and v.unsupported_numbers:
                for raw in v.unsupported_numbers[:5]:
                    digits = "".join(ch for ch in raw if ch.isdigit())
                    print(f"  '{raw}' -> digits {digits[:24]}; in evidence: {digits[:24] in evidence}")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "05")))
