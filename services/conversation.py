"""Short per-chat conversation memory for follow-up questions."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from data import config


@dataclass(slots=True)
class Turn:
    role: str
    content: str
    created_at: float = field(default_factory=time.monotonic)


class ConversationStore:
    """Keep the last few user/assistant texts per chat.

    Tool calls and raw SQL are deliberately not stored; the model must re-run
    tools for every new question, including follow-ups.
    """

    def __init__(
        self,
        max_messages: int = config.MAX_HISTORY_TURNS,
        ttl_seconds: float = config.HISTORY_TTL_SECONDS,
        max_chars_per_message: int = 2000,
    ) -> None:
        self.max_messages = max(2, max_messages)
        self.ttl_seconds = ttl_seconds
        self.max_chars_per_message = max_chars_per_message
        self._chats: dict[int, deque[Turn]] = {}

    def _prune(self, chat_id: int) -> deque[Turn]:
        turns = self._chats.setdefault(chat_id, deque(maxlen=self.max_messages))
        cutoff = time.monotonic() - self.ttl_seconds
        while turns and turns[0].created_at < cutoff:
            turns.popleft()
        return turns

    def add_user(self, chat_id: int, text: str) -> None:
        self._append(chat_id, "user", text)

    def add_assistant(self, chat_id: int, text: str) -> None:
        self._append(chat_id, "assistant", text)

    def _append(self, chat_id: int, role: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if len(text) > self.max_chars_per_message:
            text = text[: self.max_chars_per_message].rstrip() + "…"
        self._prune(chat_id).append(Turn(role=role, content=text))

    def history(self, chat_id: int) -> list[dict[str, str]]:
        return [
            {"role": turn.role, "content": turn.content}
            for turn in self._prune(chat_id)
        ]

    def clear(self, chat_id: int) -> None:
        self._chats.pop(chat_id, None)

    def active_chats(self) -> int:
        return len(self._chats)


class LanguageStore:
    """Optional per-chat language override; ``auto`` means detect per message."""

    def __init__(self) -> None:
        self._values: dict[int, str] = {}

    def get(self, chat_id: int) -> str | None:
        value = self._values.get(chat_id)
        return value if value in {"ru", "uz"} else None

    def set(self, chat_id: int, language: str) -> None:
        if language in {"ru", "uz"}:
            self._values[chat_id] = language
        else:
            self._values.pop(chat_id, None)

    def clear(self, chat_id: int) -> None:
        self._values.pop(chat_id, None)


class ChatLocks:
    """Allow at most one in-flight question per chat."""

    def __init__(self) -> None:
        import asyncio

        self._locks: dict[int, asyncio.Lock] = {}

    async def try_acquire(self, chat_id: int) -> bool:
        import asyncio

        lock = self._locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[chat_id] = lock
        if lock.locked():
            return False
        await lock.acquire()
        return True

    def release(self, chat_id: int) -> None:
        lock = self._locks.get(chat_id)
        if lock is not None and lock.locked():
            lock.release()
