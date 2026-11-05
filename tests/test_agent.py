from __future__ import annotations

import json

import pytest

from data import config
from services.agent import Agent, AgentError
from services.database import Database
from services.llm import LLMResponse
from services.tools import ToolRunner


class FakeLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    async def chat(self, messages, tools=None, **kwargs) -> LLMResponse:
        self.calls.append(messages)
        if not self.responses:
            raise AssertionError("FakeLLM ran out of responses")
        return self.responses.pop(0)


def tool_call(name: str, arguments: dict, call_id: str = "call_1") -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            }
        ],
        model="fake-model",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )


def final(text: str) -> LLMResponse:
    return LLMResponse(
        content=text,
        tool_calls=[],
        model="fake-model",
        usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    )


@pytest.fixture()
def database():
    if not config.DB_PATH.is_file():
        pytest.skip(f"DuckDB file not found: {config.DB_PATH}")
    db = Database(config.DB_PATH)
    db.connect()
    yield db
    db.close()


async def test_agent_uses_sql_result(database) -> None:
    llm = FakeLLM(
        [
            tool_call("run_sql", {"query": "SELECT COUNT(*) AS n FROM deals"}),
            final("📊 Всего 500 000 сделок.\n\nОснование: deals_enriched; строк: 1."),
        ]
    )
    agent = Agent(database, llm, tools=ToolRunner(database))

    answer = await agent.answer("Сколько всего сделок?", "ru")

    assert answer.guardrail_ok is True
    assert answer.regenerated is False
    assert answer.tool_calls == 1
    assert "500 000" in answer.text
    assert answer.sql_queries == ["SELECT COUNT(*) AS n FROM deals"]
    assert answer.tables == ["deals"]
    assert answer.usage["total_tokens"] == 45


async def test_agent_does_not_disguise_verification_failure_as_no_data(database) -> None:
    llm = FakeLLM(
        [
            tool_call("run_sql", {"query": "SELECT 1 AS n"}),
            final("📊 Всего 999 999 сделок.\n\nОснование: deals_enriched; строк: 1."),
            final("В данных реестра ответа на этот вопрос нет."),
        ]
    )
    agent = Agent(database, llm, tools=ToolRunner(database))

    with pytest.raises(AgentError) as error:
        await agent.answer("Сколько всего сделок?", "ru")
    assert error.value.outcome == "verification_failed"
    assert len(llm.calls) == 3


async def test_agent_forces_a_tool_call(database) -> None:
    llm = FakeLLM(
        [
            final("📊 Всего 999 999 сделок."),
            tool_call("run_sql", {"query": "SELECT COUNT(*) AS n FROM deals"}),
            final("📊 Всего 500 000 сделок.\n\nОснование: deals_enriched; строк: 1."),
        ]
    )
    agent = Agent(database, llm, tools=ToolRunner(database))

    answer = await agent.answer("Сколько всего сделок?", "ru")

    assert answer.tool_calls == 1
    assert answer.no_answer is False
    assert "500 000" in answer.text
    assert len(llm.calls) == 3


async def test_tool_error_is_returned_to_model(database) -> None:
    llm = FakeLLM(
        [
            tool_call("run_sql", {"query": "DELETE FROM deals"}),
            final("В данных реестра ответа на этот вопрос нет."),
        ]
    )
    agent = Agent(database, llm, tools=ToolRunner(database))

    with pytest.raises(AgentError) as error:
        await agent.answer("Удали все сделки", "ru")
    assert error.value.outcome == "execution_failed"
    tool_messages = [message for message in llm.calls[1] if message.get("role") == "tool"]
    assert "only a single read-only" in tool_messages[0]["content"]


async def test_lookup_only_answer_names_lookup_tables(database) -> None:
    llm = FakeLLM(
        [
            tool_call("search_company", {"name_or_inn": "986932945"}),
            final(
                "📊 Компания «Ko‘rak Kimyo» MChJ — продавец, ИНН 986932945.\n\n"
                "Основание: participants; ИНН 986932945."
            ),
        ]
    )
    agent = Agent(database, llm, tools=ToolRunner(database))

    answer = await agent.answer("Что за компания с ИНН 986932945?", "ru")

    assert answer.no_answer is False
    assert answer.tables == ["brokers", "participants"]
    assert "Основание" in answer.text


class FailingTools:
    async def run(self, name: str, arguments: dict) -> str:
        return json.dumps(
            {"ok": False, "tool": name, "error": "invalid value 999999"}
        )


async def test_failed_tool_result_is_not_evidence(database) -> None:
    llm = FakeLLM(
        [
            tool_call("run_sql", {"query": "SELECT broken"}),
            final("📊 Всего 999 999 сделок.\n\nОснование: deals; строк: 1."),
            final("В данных реестра ответа на этот вопрос нет."),
        ]
    )
    agent = Agent(database, llm, tools=FailingTools())

    with pytest.raises(AgentError) as error:
        await agent.answer("Сколько всего сделок?", "ru")
    assert error.value.outcome == "execution_failed"


async def test_budget_exhaustion_reserves_synthesis(database):
    class BudgetLLM(FakeLLM):
        async def chat(self, messages, tools=None, **kwargs):
            if len(self.calls) == 2:
                assert tools is None
            else:
                assert tools
            return await super().chat(messages, tools, **kwargs)
    llm = BudgetLLM([
        tool_call('run_sql', {'query': 'SELECT COUNT(*) AS n FROM deals'}),
        tool_call('run_sql', {'query': 'SELECT COUNT(*) AS n FROM deals'}),
        final('Всего 500 000 сделок.'),
    ])
    answer = await Agent(database, llm, max_tool_rounds=2).answer('Сколько сделок?', 'ru')
    assert answer.outcome == 'answered'
    assert len(llm.calls) == 3
    assert answer.cache_hits == 1
    assert answer.cache_misses == 1
    assert answer.trace[-1]['phase'] == 'synthesis'


async def test_structured_partial_answer_verifies_facts(database):
    llm = FakeLLM([
        tool_call('run_sql', {'query': 'SELECT COUNT(*) AS n FROM deals'}),
        final(json.dumps({'text': 'Всего 500 000 сделок. Прибыль неизвестна.',
                          'coverage': [{'request': 'count', 'status': 'answered'},
                                       {'request': 'profit', 'status': 'unavailable', 'reason': 'no costs'}],
                          'metrics': {}}, ensure_ascii=False)),
    ])
    answer = await Agent(database, llm).answer('Сколько сделок и прибыль?', 'ru')
    assert answer.outcome == 'partial'
    assert not answer.no_answer
    assert len(answer.coverage) == 2


async def test_cached_result_remains_evidence_in_new_turn(database):
    runner = ToolRunner(database)
    llm = FakeLLM([
        tool_call('run_sql', {'query': 'SELECT 123456 AS total'}), final('123456 сум'),
        tool_call('run_sql', {'query': 'SELECT 123456 AS total'}), final('123456 сум'),
    ])
    agent = Agent(database, llm, runner)
    assert (await agent.answer('Сумма?', 'ru')).cache_misses == 1
    answer = await agent.answer('Сумма?', 'ru')
    assert answer.cache_hits == 1
    assert answer.guardrail_ok


async def test_empty_reserved_synthesis_is_execution_failure(database):
    llm = FakeLLM([tool_call('run_sql', {'query': 'SELECT 1'}),
                   tool_call('run_sql', {'query': 'SELECT 2'}), final('')])
    with pytest.raises(AgentError) as error:
        await Agent(database, llm, max_tool_rounds=2).answer('Count?', 'ru')
    assert error.value.outcome == 'execution_failed'


async def test_truncated_draft_gets_larger_final_budget(database):
    response = final('{"text": "truncated')
    response.finish_reason = 'length'
    class LengthLLM(FakeLLM):
        async def chat(self, messages, tools=None, **kwargs):
            if len(self.calls) == 2:
                assert tools is None
                assert kwargs['max_tokens'] == config.LLM_FINAL_MAX_TOKENS
            return await super().chat(messages, tools, **kwargs)
    llm = LengthLLM([tool_call('run_sql', {'query': 'SELECT 12345 AS amount'}),
                     response, final('12345 сум')])
    answer = await Agent(database, llm).answer('Amount?', 'ru')
    assert answer.guardrail_ok
    assert not answer.regenerated
    assert len(llm.calls) == 3
