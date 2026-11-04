from __future__ import annotations

from services.language import RU, UZ, detect_language


def test_russian_cyrillic() -> None:
    assert detect_language("Сколько всего сделок заключено в 2024 году?") == RU


def test_uzbek_latin_markers() -> None:
    assert detect_language("2024-yilda jami nechta bitim tuzilgan?") == UZ
    assert detect_language("Eng ko‘p bitim qaysi broker orqali o‘tgan?") == UZ


def test_uzbek_apostrophes() -> None:
    assert detect_language("kaustik soda narxi qanday?") == UZ


def test_fallback_for_ambiguous_text() -> None:
    assert detect_language("185158", fallback=RU) == RU
    assert detect_language("185158", fallback=UZ) == UZ
