"""Small, dependency-free RU/UZ language detection helpers.

The hackathon questions arrive in Russian (usually Cyrillic) or Uzbek (usually
Latin script).  We auto-detect the language of every question and reply in the
same language.  A user can override the choice with ``/lang``.
"""

from __future__ import annotations

import re

RU = "ru"
UZ = "uz"

# Words that are strong signals for Uzbek Latin script.  Keep them lowercase
# and without apostrophes; ``normalize`` removes the various apostrophe forms.
UZ_MARKERS = {
    "assalom", "salom", "qanday", "qanaqa", "qancha", "nechta", "necha",
    "qaysi", "qayerda", "qachon", "yilda", "yil", "oyda", "kun", "sana",
    "bitim", "bitimlar", "shartnoma", "shartnomalar", "tovar", "mahsulot",
    "sotuvchi", "xaridor", "broker", "kompaniya", "korxona", "jami",
    "eng", "katta", "kichik", "kop", "koʻp", "kam", "summa", "soʻm",
    "som", "dollar", "kurs", "hisobot", "maʼlumot", "malumot", "reyestr",
    "savol", "javob", "top", "toping", "ber", "bering", "kerak", "bolgan",
    "boʻlgan", "tuzilgan", "sotilgan", "sotib", "olingan", "davlat",
    "viloyat", "shahar", "tuman", "hudud", "foiz", "ulush", "oʻrtacha",
    "ortacha", "narx", "qiymat", "hajm", "tonna", "kilogramm", "litr",
}

# Uzbek-specific Latin characters.  A single one is a very strong signal.
UZ_CHARS = set("ʻʼ‘’")

CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
WORD_RE = re.compile(r"[a-zA-Zʻʼ‘’'‘]+")


def normalize(text: str) -> str:
    """Normalise apostrophes/case for keyword matching."""

    value = text.lower()
    for char in ("ʻ", "ʼ", "‘", "’", "`", "´"):
        value = value.replace(char, "'")
    return value


def detect_language(text: str, fallback: str = RU) -> str:
    """Return ``ru`` or ``uz`` for a user message.

    Cyrillic wins over Latin markers because Russian questions are mostly
    Cyrillic and Uzbek Cyrillic is rare in this competition.  For Latin text we
    count Uzbek marker words and Uzbek-specific characters.
    """

    text = (text or "").strip()
    if not text:
        return fallback

    cyrillic = len(CYRILLIC_RE.findall(text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if cyrillic and cyrillic >= latin * 0.5:
        return RU

    lowered = normalize(text)
    if any(char in lowered for char in UZ_CHARS):
        return UZ

    words = set(WORD_RE.findall(lowered))
    if words & UZ_MARKERS:
        return UZ

    # Common Uzbek suffixes that rarely occur in Russian Latin transliteration.
    if re.search(r"\b\w+(?:lari|larini|larida|dagi|yida|idan|ning)\b", lowered):
        return UZ

    return fallback


def language_name(language: str) -> str:
    return "Uzbek" if language == UZ else "Russian"


def is_uzbek(language: str) -> bool:
    return language == UZ
