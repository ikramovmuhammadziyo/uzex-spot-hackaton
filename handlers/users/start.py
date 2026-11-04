from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from services.language import RU
from services.messages import START
from services.runtime import get_runtime

router = Router(name="start")


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
                InlineKeyboardButton(text="🇺🇿 Oʻzbekcha", callback_data="lang:uz"),
            ]
        ]
    )


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    runtime = get_runtime()
    language = runtime.languages.get(message.chat.id) or RU
    await message.answer(
        START[language],
        reply_markup=language_keyboard(),
        parse_mode="HTML",
    )
