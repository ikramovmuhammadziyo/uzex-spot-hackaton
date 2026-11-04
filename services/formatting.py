"""Message formatting helpers."""

from __future__ import annotations

import html
import re

TELEGRAM_LIMIT = 4096
SAFE_CHUNK = 3900


def split_message(text: str, limit: int = SAFE_CHUNK) -> list[str]:
    """Split a long answer into Telegram-sized chunks without breaking words."""

    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        # Prefer paragraph, then line, then sentence, then space boundaries.
        split_at = window.rfind("\n\n")
        if split_at < limit // 2:
            split_at = window.rfind("\n")
        if split_at < limit // 2:
            split_at = window.rfind(". ")
            if split_at != -1:
                split_at += 1
        if split_at < limit // 2:
            split_at = window.rfind(" ")
        if split_at <= 0:
            split_at = limit

        chunk = remaining[:split_at].rstrip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].lstrip()

    if remaining:
        chunks.append(remaining)
    return chunks


def escape_html(text: str) -> str:
    return html.escape(text or "", quote=False)


def compact_whitespace(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text or "").strip()


def shorten(text: str, limit: int) -> str:
    text = compact_whitespace(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"
