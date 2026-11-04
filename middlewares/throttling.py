from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from data import config
from services.language import RU, detect_language
from services.messages import BUSY


class ThrottlingMiddleware(BaseMiddleware):
    """Very small per-user flood guard.

    The handler itself also holds a per-chat lock, so a user cannot run two
    expensive LLM questions at once.
    """

    def __init__(self, rate: float = config.RATE_LIMIT_SECONDS) -> None:
        self.rate = max(0.2, rate)
        self._last: dict[int, float] = {}
        self._last_cleanup = time.monotonic()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.from_user is not None:
            user_id = event.from_user.id
            now = time.monotonic()
            last = self._last.get(user_id, 0.0)
            if now - last < self.rate:
                # Do not spam: only notify if the previous message was recent
                # enough to be perceived as part of the same action.
                if now - last > self.rate / 2:
                    language = detect_language(event.text or "", RU)
                    try:
                        await event.answer(BUSY[language], parse_mode=None)
                    except Exception:
                        pass
                return None

            self._last[user_id] = now
            if now - self._last_cleanup > 300:
                cutoff = now - 300
                self._last = {key: value for key, value in self._last.items() if value >= cutoff}
                self._last_cleanup = now

        return await handler(event, data)
