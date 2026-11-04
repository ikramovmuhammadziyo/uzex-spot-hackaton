from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from services.language import RU, detect_language
from services.messages import RESET
from services.runtime import get_runtime

router = Router(name="reset")


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    runtime = get_runtime()
    language = runtime.languages.get(message.chat.id) or detect_language(message.text or "", RU)
    runtime.conversations.clear(message.chat.id)
    await message.answer(RESET[language], parse_mode=None)
