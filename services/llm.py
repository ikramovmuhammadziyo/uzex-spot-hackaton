"""Minimal async client for any OpenAI-compatible /chat/completions API.

Works with OpenAI, OpenRouter, DeepSeek, Groq, a local Ollama/LM Studio server,
or any other provider that implements the OpenAI chat-completions + tool-calling
contract.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from data import config

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """The language model could not produce a response."""


@dataclass(slots=True)
class LLMResponse:
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    finish_reason: str = ""

    @property
    def message(self) -> dict[str, Any]:
        """A clean assistant message suitable for the next API call."""

        payload: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            payload["tool_calls"] = self.tool_calls
        return payload


def _parse_extra_headers(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return {str(key): str(value) for key, value in parsed.items()}

    headers: dict[str, str] = {}
    for chunk in raw.replace(";", "\n").splitlines():
        if "=" in chunk:
            key, value = chunk.split("=", 1)
        elif ":" in chunk:
            key, value = chunk.split(":", 1)
        else:
            continue
        key = key.strip()
        value = value.strip()
        if key:
            headers[key] = value
    return headers


class LLMClient:
    def __init__(
        self,
        api_key: str = config.LLM_API_KEY,
        base_url: str = config.LLM_BASE_URL,
        model: str = config.LLM_MODEL,
        temperature: float = config.LLM_TEMPERATURE,
        max_tokens: int = config.LLM_MAX_TOKENS,
        timeout: float = config.LLM_TIMEOUT_SECONDS,
        max_retries: int = config.LLM_MAX_RETRIES,
        extra_headers: dict[str, str] | None = None,
        reasoning_effort: str = config.LLM_REASONING_EFFORT,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.reasoning_effort = (reasoning_effort or "").strip().lower()
        self._client: httpx.AsyncClient | None = None

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        headers.update(extra_headers or _parse_extra_headers(config.LLM_EXTRA_HEADERS))
        self._headers = headers

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=self.timeout,
                    write=30.0,
                    pool=10.0,
                ),
                headers=self._headers,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
            "stream": False,
        }
        if self.reasoning_effort:
            # Gemini 3.8 Flash maps this to its thinking level. Other
            # OpenAI-compatible providers may ignore or reject it, so it is
            # opt-in through LLM_REASONING_EFFORT.
            payload["reasoning_effort"] = self.reasoning_effort
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        if not self.configured:
            raise LLMError("LLM_API_KEY is not configured")

        payload = self._build_payload(messages, tools, temperature, max_tokens)

        url = f"{self.base_url}/chat/completions"
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await self._http().post(url, json=payload)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise LLMError(f"network error: {exc}") from exc

            if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                retry_after = response.headers.get("retry-after")
                try:
                    delay = float(retry_after) if retry_after else 1.5 * (attempt + 1)
                except ValueError:
                    delay = 1.5 * (attempt + 1)
                logger.warning(
                    "LLM HTTP %s, retrying in %.1fs (attempt %s/%s)",
                    response.status_code,
                    delay,
                    attempt + 1,
                    self.max_retries,
                )
                await asyncio.sleep(min(delay, 10.0))
                continue

            if response.status_code >= 400:
                body = response.text[:1000]
                raise LLMError(f"HTTP {response.status_code}: {body}")

            try:
                data = response.json()
            except ValueError as exc:
                raise LLMError("LLM returned invalid JSON") from exc

            return self._parse_response(data)

        raise LLMError(f"LLM request failed: {last_error}")

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            error = data.get("error")
            raise LLMError(f"LLM response has no choices: {error or data}")

        choice = choices[0] or {}
        message = choice.get("message") or {}
        content = message.get("content") or ""
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(str(item))
            content = "".join(parts)
        content = str(content).strip()

        raw_calls = message.get("tool_calls") or []
        tool_calls: list[dict[str, Any]] = []
        if isinstance(raw_calls, list):
            for index, call in enumerate(raw_calls):
                if not isinstance(call, dict):
                    continue
                function = call.get("function") or {}
                name = str(function.get("name") or "").strip()
                if not name:
                    continue
                arguments = function.get("arguments")
                if isinstance(arguments, (dict, list)):
                    arguments = json.dumps(arguments, ensure_ascii=False)
                if arguments is None:
                    arguments = "{}"
                tool_calls.append(
                    {
                        "id": str(call.get("id") or f"call_{index}_{uuid.uuid4().hex[:8]}"),
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": str(arguments),
                        },
                    }
                )

        usage = data.get("usage") or {}
        response = LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage if isinstance(usage, dict) else {},
            model=str(data.get("model") or self.model),
            finish_reason=str(choice.get("finish_reason") or ""),
        )
        logger.debug(
            "LLM response model=%s finish=%s tool_calls=%s tokens=%s",
            response.model,
            response.finish_reason,
            len(response.tool_calls),
            usage,
        )
        return response
