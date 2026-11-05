"""Configuration for the UZEX Telegram bot.

All values come from environment variables (a local ``.env`` file is loaded
automatically).  See ``.env.dist`` for the full list.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _as_int_list(raw: str) -> list[int]:
    values: list[int] = []
    for chunk in raw.replace(";", ",").replace(" ", ",").split(","):
        chunk = chunk.strip()
        if chunk:
            try:
                values.append(int(chunk))
            except ValueError:
                continue
    return values


def _as_path(raw: str, default: Path) -> Path:
    path = Path(raw).expanduser() if raw else default
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def _as_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _as_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMINS = _as_int_list(os.getenv("ADMINS", ""))

# ---------------------------------------------------------------------------
# Data / DuckDB
# ---------------------------------------------------------------------------
DB_PATH = _as_path(os.getenv("DB_PATH", "data/uzex.duckdb"), BASE_DIR / "data" / "uzex.duckdb")
SQL_TIMEOUT_SECONDS = _as_float("SQL_TIMEOUT_SECONDS", 15.0)
SQL_MAX_ROWS = _as_int("SQL_MAX_ROWS", 100)
TOOL_CACHE_ENTRIES = _as_int("TOOL_CACHE_ENTRIES", 256)
TOOL_CACHE_BYTES = _as_int("TOOL_CACHE_BYTES", 8 * 1024 * 1024)

# Facts used by the prompt and by the deterministic guardrails.
DEALS_MIN_DATE = "2022-01-03"
DEALS_MAX_DATE = "2026-10-30"
RATES_MIN_DATE = "2022-01-01"
RATES_MAX_DATE = "2026-10-31"
TOTAL_DEALS = 500_000

# ---------------------------------------------------------------------------
# LLM (any OpenAI-compatible /chat/completions endpoint)
# ---------------------------------------------------------------------------
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
LLM_TEMPERATURE = _as_float("LLM_TEMPERATURE", 0.0)
LLM_MAX_TOKENS = _as_int("LLM_MAX_TOKENS", 4096)
LLM_FINAL_MAX_TOKENS = _as_int("LLM_FINAL_MAX_TOKENS", 8192)
LLM_TIMEOUT_SECONDS = _as_float("LLM_TIMEOUT_SECONDS", 60.0)
LLM_MAX_RETRIES = _as_int("LLM_MAX_RETRIES", 2)
LLM_MAX_TOOL_ROUNDS = _as_int("LLM_MAX_TOOL_ROUNDS", 6)
LLM_EXTRA_HEADERS = os.getenv("LLM_EXTRA_HEADERS", "").strip()
# Optional OpenAI-style reasoning effort (low/medium/high). Gemini 3.8 Flash
# uses medium by default; "low" keeps tool-calling answers fast.
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "").strip().lower()

# ---------------------------------------------------------------------------
# Bot behaviour
# ---------------------------------------------------------------------------
AGENT_TIMEOUT_SECONDS = _as_float("AGENT_TIMEOUT_SECONDS", 75.0)
MAX_QUESTION_CHARS = _as_int("MAX_QUESTION_CHARS", 2000)
MAX_HISTORY_TURNS = _as_int("MAX_HISTORY_TURNS", 8)
HISTORY_TTL_SECONDS = _as_float("HISTORY_TTL_SECONDS", 1800.0)
RATE_LIMIT_SECONDS = _as_float("RATE_LIMIT_SECONDS", 1.5)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR = _as_path(os.getenv("LOG_DIR", "logs"), BASE_DIR / "logs")
QA_LOG_PATH = _as_path(os.getenv("QA_LOG_PATH", "logs/qa.jsonl"), BASE_DIR / "logs" / "qa.jsonl")

TASHKENT_TZ = timezone(timedelta(hours=5))


def now_tashkent() -> datetime:
    """Current time in Tashkent (UTC+5, no DST)."""

    return datetime.now(TASHKENT_TZ)
