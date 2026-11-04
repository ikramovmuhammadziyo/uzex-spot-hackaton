from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import BotCommand

from data import config

logger = logging.getLogger(__name__)


async def set_default_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Boshlash / Начать"),
            BotCommand(command="help", description="Yordam / Помощь"),
            BotCommand(command="lang", description="Til / Язык (ru, uz, auto)"),
            BotCommand(command="reset", description="Suhbatni tozalash / Сбросить контекст"),
        ]
    )


async def notify_admins(bot: Bot, text: str) -> None:
    if not config.ADMINS:
        logger.info("ADMINS is empty; startup notification skipped")
        return
    for admin_id in config.ADMINS:
        try:
            await bot.send_message(admin_id, text, parse_mode=None)
        except Exception:
            logger.exception("could not notify admin %s", admin_id)
