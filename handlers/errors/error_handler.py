from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import ErrorEvent, Message

from services.language import RU
from services.messages import GENERIC_ERROR

logger = logging.getLogger(__name__)
router = Router(name="errors")


@router.error()
async def error_handler(event: ErrorEvent) -> bool:
    logger.exception("unhandled update error", exc_info=event.exception)

    update = event.update
    message: Message | None = update.message
    if message is None and update.callback_query is not None:
        callback_message = update.callback_query.message
        if isinstance(callback_message, Message):
            message = callback_message

    if message is not None:
        try:
            await message.answer(GENERIC_ERROR[RU], parse_mode=None)
        except Exception:  # pragma: no cover - best effort
            logger.exception("could not send error message")
    return True
