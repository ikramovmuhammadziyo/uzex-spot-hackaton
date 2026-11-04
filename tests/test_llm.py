from __future__ import annotations

import pytest

from services.llm import LLMClient, LLMError, _parse_extra_headers


def make_client(api_key: str = "test-key") -> LLMClient:
    return LLMClient(
        api_key=api_key,
        base_url="http://localhost:9999/v1",
        model="mock-model",
        reasoning_effort="",
    )


def test_parse_tool_call_response() -> None:
    client = make_client()
    response = client._parse_response(
        {
            "model": "mock-model",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "run_sql",
                                    "arguments": {"query": "SELECT 1"},
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }
    )

    assert response.content == ""
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls
    assert response.tool_calls[0]["id"] == "call_1"
    assert response.tool_calls[0]["function"]["name"] == "run_sql"
    assert response.tool_calls[0]["function"]["arguments"] == '{"query": "SELECT 1"}'
    assert response.message["tool_calls"] == response.tool_calls
    assert response.usage["total_tokens"] == 3


def test_preserves_gemini_thought_signature() -> None:
    client = make_client()
    signature = {"google": {"thought_signature": "opaque-signature"}}
    response = client._parse_response(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "run_sql",
                                    "arguments": '{"query": "SELECT 1"}',
                                },
                                "extra_content": signature,
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
    )

    assert response.tool_calls[0]["extra_content"] == signature
    assert response.message["tool_calls"][0]["extra_content"] == signature


def test_parse_list_content() -> None:
    client = make_client()
    response = client._parse_response(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "Привет"},
                            {"type": "text", "text": ", мир"},
                        ],
                    }
                }
            ]
        }
    )
    assert response.content == "Привет, мир"


def test_missing_choices_raises() -> None:
    client = make_client()
    with pytest.raises(LLMError):
        client._parse_response({"error": {"message": "bad model"}})


def test_extra_headers_json_and_pairs() -> None:
    assert _parse_extra_headers('{"X-Test": "1"}') == {"X-Test": "1"}
    assert _parse_extra_headers("A=1; B=2") == {"A": "1", "B": "2"}
    assert _parse_extra_headers("") == {}


def test_authorization_header_and_configured_flag() -> None:
    client = LLMClient(
        api_key="secret",
        base_url="http://localhost/v1",
        model="mock",
        extra_headers={"X-Test": "yes"},
    )
    assert client.configured is True
    assert client._headers["Authorization"] == "Bearer secret"
    assert client._headers["X-Test"] == "yes"

    unconfigured = make_client(api_key="")
    assert unconfigured.configured is False


def test_payload_includes_tools_and_tool_choice() -> None:
    client = make_client()
    tools = [{"type": "function", "function": {"name": "run_sql"}}]
    payload = client._build_payload([{"role": "user", "content": "hi"}], tools)
    assert payload["model"] == "mock-model"
    assert payload["tools"] == tools
    assert payload["tool_choice"] == "auto"
    assert "reasoning_effort" not in payload


def test_payload_includes_reasoning_effort_when_configured() -> None:
    client = LLMClient(
        api_key="test-key",
        base_url="http://localhost/v1",
        model="gemini-3.8-flash",
        reasoning_effort="LOW",
    )
    payload = client._build_payload([{"role": "user", "content": "hi"}])
    assert payload["reasoning_effort"] == "low"
