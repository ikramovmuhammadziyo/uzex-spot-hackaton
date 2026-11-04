from __future__ import annotations

import platform
import sys

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from data import config
from services.database import DatabaseError
from services.language import RU, detect_language
from services.messages import HEALTH_DENIED
from services.runtime import get_runtime

router = Router(name="health")


@router.message(Command("health"))
async def cmd_health(message: Message) -> None:
    runtime = get_runtime()
    language = runtime.languages.get(message.chat.id) or detect_language(message.text or "", RU)

    if (
        not config.ADMINS
        or message.from_user is None
        or message.from_user.id not in config.ADMINS
    ):
        await message.answer(HEALTH_DENIED[language], parse_mode=None)
        return

    lines = ["🩺 UZEX bot health", ""]
    lines.append(f"Python: {sys.version.split()[0]} on {platform.platform()}")
    lines.append(f"DB: {config.DB_PATH}")
    lines.append(f"DB size: {runtime.database.file_size_mb():.1f} MB")

    if runtime.database.available:
        try:
            counts = await runtime.database.table_counts()
            lines.append(
                "Rows: "
                + ", ".join(f"{table}={count:,}".replace(",", " ") for table, count in counts.items())
            )
        except DatabaseError as exc:
            lines.append(f"DB queries: ERROR ({exc})")
    else:
        lines.append(f"DB: UNAVAILABLE ({runtime.database.last_error})")

    lines.append(f"LLM model: {config.LLM_MODEL}")
    lines.append(f"LLM base: {config.LLM_BASE_URL}")
    lines.append(f"LLM key: {'configured' if runtime.llm.configured else 'MISSING'}")
    uptime = int(__import__("time").monotonic() - runtime.started_at)
    hours, remainder = divmod(uptime, 3600)
    minutes, seconds = divmod(remainder, 60)
    lines.append(f"Uptime: {hours:02d}:{minutes:02d}:{seconds:02d}")
    lines.append(f"Active chats: {runtime.conversations.active_chats()}")

    await message.answer("\n".join(lines), parse_mode=None)
