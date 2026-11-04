from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from services.language import RU, detect_language
from services.messages import HELP
from services.runtime import get_runtime

router = Router(name="help")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    runtime = get_runtime()
    language = runtime.languages.get(message.chat.id) or detect_language(message.text or "", RU)
    await message.answer(HELP[language], parse_mode="HTML")
