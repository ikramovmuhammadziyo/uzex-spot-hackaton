from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from services.language import RU, UZ, detect_language
from services.messages import (
    LANG_AUTO,
    LANG_PROMPT,
    LANG_SET,
    LANG_UNKNOWN,
)
from services.runtime import get_runtime

from .start import language_keyboard

router = Router(name="language")


@router.message(Command("lang"))
async def cmd_lang(message: Message, command: CommandObject) -> None:
    runtime = get_runtime()
    argument = (command.args or "").strip().lower()

    if not argument:
        language = runtime.languages.get(message.chat.id) or detect_language(message.text or "", RU)
        await message.answer(
            LANG_PROMPT[language],
            reply_markup=language_keyboard(),
            parse_mode="HTML",
        )
        return

    if argument in {"ru", "rus", "russian", "рус", "русский"}:
        runtime.languages.set(message.chat.id, RU)
        await message.answer(LANG_SET[RU], parse_mode=None)
        return
    if argument in {"uz", "uzb", "uzbek", "o'zbek", "oʻzbek", "узбек"}:
        runtime.languages.set(message.chat.id, UZ)
        await message.answer(LANG_SET[UZ], parse_mode=None)
        return
    if argument in {"auto", "avto", "авто"}:
        language = runtime.languages.get(message.chat.id) or detect_language(message.text or "", RU)
        runtime.languages.clear(message.chat.id)
        await message.answer(LANG_AUTO[language], parse_mode=None)
        return

    await message.answer(LANG_UNKNOWN[RU], parse_mode=None)


@router.callback_query(F.data.startswith("lang:"))
async def choose_language(callback: CallbackQuery) -> None:
    runtime = get_runtime()
    value = (callback.data or "").split(":", 1)[1]
    if value not in {RU, UZ}:
        await callback.answer(LANG_UNKNOWN[RU])
        return

    runtime.languages.set(callback.message.chat.id if callback.message else callback.from_user.id, value)
    await callback.answer()
    if callback.message:
        await callback.message.answer(LANG_SET[value], parse_mode=None)
