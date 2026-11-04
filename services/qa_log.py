"""Append-only Q&A log (JSON Lines) for debugging and the solution write-up."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime
from typing import Any

from data import config

logger = logging.getLogger(__name__)
_LOCK = threading.Lock()


def hash_user_id(user_id: int | None) -> str:
    if user_id is None:
        return "unknown"
    digest = hashlib.sha256(f"uzex-bot:{user_id}".encode("utf-8")).hexdigest()
    return digest[:12]


def log_qa(record: dict[str, Any]) -> None:
    """Write one JSON object per line. Never let logging break an answer."""

    payload = {
        "ts": datetime.now(config.TASHKENT_TZ).isoformat(timespec="seconds"),
        **record,
    }
    try:
        config.QA_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with _LOCK:
            with config.QA_LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except Exception:  # pragma: no cover - logging must not crash the bot
        logger.exception("could not write QA log")
