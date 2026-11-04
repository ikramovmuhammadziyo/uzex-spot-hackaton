from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from data import config

if not config.BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is not set. Copy .env.dist to .env and put the token from @BotFather there."
    )

bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dispatcher = Dispatcher(storage=MemoryStorage())
dp = dispatcher  # short alias used by the templates
