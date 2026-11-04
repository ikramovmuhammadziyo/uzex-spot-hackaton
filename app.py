from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from data import config
from handlers import setup_routers
from loader import bot, dp
from middlewares import setup_middlewares
from services.database import Database, DatabaseError
from services.llm import LLMClient
from services.runtime import create_runtime
from utils.misc.logging import setup_logging
from utils.set_commands import notify_admins, set_default_commands

logger = logging.getLogger(__name__)


async def main() -> None:
    setup_logging()
    logger.info("starting UZEX bot")

    database = Database(config.DB_PATH)
    database_status = "not connected"
    try:
        database.connect()
        counts = await database.table_counts()
        database_status = "ok, " + ", ".join(
            f"{table}={count:,}".replace(",", " ") for table, count in counts.items()
        )
        logger.info("database ready: %s", database_status)
    except DatabaseError as exc:
        database_status = f"UNAVAILABLE: {exc}"
        logger.critical("database unavailable: %s", exc)

    llm = LLMClient()
    runtime = create_runtime(database, llm)
    logger.info(
        "LLM model=%s base=%s key=%s",
        config.LLM_MODEL,
        config.LLM_BASE_URL,
        "configured" if llm.configured else "MISSING",
    )

    setup_middlewares(dp)
    setup_routers(dp)
    await set_default_commands(bot)

    await notify_admins(
        bot,
        "🤖 UZEX bot started\n"
        f"DB: {database_status}\n"
        f"LLM: {config.LLM_MODEL} ({'key ok' if llm.configured else 'key MISSING'})\n"
        f"API: {config.LLM_BASE_URL}",
    )

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        logger.info("stopping UZEX bot")
        await llm.close()
        database.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
