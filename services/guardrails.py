"""Deterministic post-generation checks.

The LLM is allowed to phrase an answer, but every number, date, INN, broker
code and company name in the substantive part of the answer must be traceable
to a tool result from the same conversation turn.  This module implements the
check without importing aiogram, DuckDB or any network library, which keeps it
easy to unit-test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .language import UZ, normalize

NO_ANSWER_RU = "В данных реестра ответа на этот вопрос нет."
NO_ANSWER_UZ = "Maʼlumotlar reyestrida bu savolga javob yoʻq."


def no_answer(language: str) -> str:
    return NO_ANSWER_UZ if language == UZ else NO_ANSWER_RU


def is_no_answer(text: str) -> bool:
    value = normalize(text or "")
    if not value.strip():
        return True
    markers = (
        "в данных реестра ответа",
        "в данных нет ответа",
        "нет данных для ответа",
        "maʼlumotlar reyestrida bu savolga javob",
        "ma'lumotlar reyestrida bu savolga javob",
        "maʼlumotlarda javob yoʻq",
        "ma'lumotlarda javob yo'q",
        "reyestrda javob yoʻq",
        "reyestrda javob yo'q",
    )
    return any(marker in value for marker in markers)


# ---------------------------------------------------------------------------
# Token extraction
# ---------------------------------------------------------------------------
DATE_ISO_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
DATE_DMY_RE = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)")
CODE_RE = re.compile(r"(?<![A-Za-z0-9])BK\d{3}(?![A-Za-z0-9])", re.IGNORECASE)
NUMBER_RE = re.compile(
    r"(?<![\w.,])"
    r"(?:\d{1,3}(?:[ \u00A0\u202F]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?![\w])"
)
GROUPED_NUMBER_RE = re.compile(
    r"(?<![\w.,])\d{1,3}(?:[., \u00A0\u202F]\d{3})+(?:[.,]\d+)?(?![\w])"
)


@dataclass(frozen=True, slots=True)
class Candidate:
    raw: str
    kind: str  # "number" | "date" | "code"
    variants: frozenset[str]


def _date_candidate(year: int, month: int, day: int) -> Candidate | None:
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    canonical = f"{year:04d}{month:02d}{day:02d}"
    return Candidate(
        raw=f"{day:02d}.{month:02d}.{year:04d}",
        kind="date",
        variants=frozenset({canonical}),
    )


def number_variants(raw: str) -> frozenset[str]:
    """Return every plausible interpretation of a formatted number.

    ``1 234``, ``1,234`` and ``1234`` all share the variant ``1234``; a decimal
    ``12,5`` also carries ``12.5`` so different formatting styles still match.
    """

    value = (
        raw.strip()
        .replace(" ", "")
        .replace("\u00a0", "")
        .replace("\u202f", "")
        .replace("−", "-")
    )
    value = value.strip("+-")
    if not value:
        return frozenset()

    digits = re.sub(r"\D", "", value)
    variants: set[str] = set()
    if digits:
        variants.add(digits)
        variants.add(str(int(digits)))
    variants.add(value)

    if "." in value or "," in value:
        without_separators = re.sub(r"[.,]", "", value)
        if without_separators:
            variants.add(without_separators)

        last_separator = max(value.rfind("."), value.rfind(","))
        if 0 <= last_separator < len(value) - 1:
            integer_part = re.sub(r"\D", "", value[:last_separator]) or "0"
            decimal_part = re.sub(r"\D", "", value[last_separator + 1 :])
            if decimal_part:
                decimal = f"{integer_part}.{decimal_part}"
                variants.add(decimal)
                trimmed = decimal.rstrip("0").rstrip(".")
                if trimmed:
                    variants.add(trimmed)

    return frozenset(item for item in variants if item)


def _candidate_from_number(raw: str) -> Candidate:
    return Candidate(raw=raw, kind="number", variants=number_variants(raw))


def extract_candidates(text: str) -> list[Candidate]:
    """Extract dates, broker codes and numbers, preserving their positions."""

    if not text:
        return []

    remaining = list(text)
    candidates: list[Candidate] = []

    def mask(start: int, end: int) -> None:
        for index in range(start, end):
            if remaining[index] not in "\r\n":
                remaining[index] = " "

    for match in DATE_ISO_RE.finditer(text):
        year, month, day = (int(part) for part in match.groups())
        candidate = _date_candidate(year, month, day)
        if candidate:
            candidates.append(candidate)
            mask(match.start(), match.end())

    partially_masked = "".join(remaining)
    for match in DATE_DMY_RE.finditer(partially_masked):
        day, month, year = (int(part) for part in match.groups())
        candidate = _date_candidate(year, month, day)
        if candidate:
            candidates.append(candidate)
            mask(match.start(), match.end())

    partially_masked = "".join(remaining)
    for match in CODE_RE.finditer(partially_masked):
        candidates.append(
            Candidate(raw=match.group(0), kind="code", variants=frozenset({match.group(0).upper()}))
        )
        mask(match.start(), match.end())

    partially_masked = "".join(remaining)
    for match in GROUPED_NUMBER_RE.finditer(partially_masked):
        candidates.append(_candidate_from_number(match.group(0)))
        mask(match.start(), match.end())

    partially_masked = "".join(remaining)
    for match in NUMBER_RE.finditer(partially_masked):
        candidates.append(_candidate_from_number(match.group(0)))

    return candidates


def is_significant(candidate: Candidate) -> bool:
    """Ignore tiny numbers (1–2 digits) but check counts, sums, years, dates."""

    if candidate.kind in {"date", "code"}:
        return True
    return any(len(re.sub(r"\D", "", value)) >= 3 for value in candidate.variants)


# ---------------------------------------------------------------------------
# Evidence index
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)


def _name_tokens(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.findall(normalize(text)) if len(token) >= 3]


class EvidenceIndex:
    """Everything a tool returned during one conversation turn."""

    def __init__(self) -> None:
        self._variants: set[str] = set()
        self._words: set[str] = set()
        self._prefixes: set[str] = set()
        self._normalized_parts: list[str] = []

    def add(
        self,
        text: str,
        *,
        numbers: bool = True,
        dates: bool = True,
        names: bool = True,
    ) -> None:
        if not text:
            return
        self._normalized_parts.append(normalize(text))
        if names:
            for token in _name_tokens(text):
                self._words.add(token)
                if len(token) >= 5:
                    self._prefixes.add(token[:5])

        for candidate in extract_candidates(text):
            if candidate.kind == "date":
                if not dates:
                    continue
                # A tool result containing 2024-01-01 also supports the year
                # 2024, which the answer normally repeats from the question.
                self._variants.add(candidate.raw[-4:])
            elif candidate.kind in {"number", "code"}:
                if not numbers:
                    continue
            self._variants.update(candidate.variants)

    def contains_number(self, candidate: Candidate) -> bool:
        return bool(candidate.variants & self._variants)

    def contains_name(self, name: str) -> bool:
        tokens = _name_tokens(name)
        if not tokens:
            return True
        for token in tokens:
            if token in self._words:
                continue
            if len(token) >= 5 and token[:5] in self._prefixes:
                continue
            return False
        return True

    @property
    def size(self) -> int:
        return len(self._variants)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
EVIDENCE_LINE_RE = re.compile(
    r"(?im)^\s*(?:🔎\s*)?(?:основание|asos|evidence|manba|источник)\s*[:\-—].*$"
)
NAME_CONTEXT_RE = re.compile(
    r"(?:компани[яиюей]|фирм[аыуе]|продавц[а-яё]*|покупател[а-яё]*|брокер[а-яё]*|"
    r"kompaniya|sotuvchi|xaridor|broker)\s*[«\"“]([^»\"”]{3,80})[»\"”]",
    re.IGNORECASE,
)
NAME_WHITELIST = {
    "основание", "asos", "evidence", "источник", "manba",
    "узбекский сум", "доллар сша", "uzs", "usd",
}


def has_evidence_line(text: str) -> bool:
    return bool(EVIDENCE_LINE_RE.search(text or ""))


def strip_evidence_lines(text: str) -> str:
    return EVIDENCE_LINE_RE.sub("", text or "").strip()


@dataclass(slots=True)
class VerificationResult:
    ok: bool
    unsupported_numbers: list[str] = field(default_factory=list)
    unsupported_names: list[str] = field(default_factory=list)
    missing_evidence: bool = False
    no_answer: bool = False
    empty: bool = False

    @property
    def needs_regeneration(self) -> bool:
        return not self.ok and not self.no_answer


def verify_answer(answer: str, evidence: EvidenceIndex, language: str) -> VerificationResult:
    answer = (answer or "").strip()
    if is_no_answer(answer):
        return VerificationResult(ok=True, no_answer=True)

    if not strip_evidence_lines(answer).strip():
        return VerificationResult(ok=False, empty=True)

    unsupported_numbers: list[str] = []
    for candidate in extract_candidates(answer):
        if not is_significant(candidate):
            continue
        if not evidence.contains_number(candidate):
            unsupported_numbers.append(candidate.raw)

    unsupported_names: list[str] = []
    for match in NAME_CONTEXT_RE.finditer(answer):
        name = match.group(1).strip()
        if normalize(name).strip() in NAME_WHITELIST:
            continue
        if not evidence.contains_name(name):
            unsupported_names.append(name)

    ok = not unsupported_numbers and not unsupported_names
    return VerificationResult(
        ok=ok,
        unsupported_numbers=_dedupe(unsupported_numbers),
        unsupported_names=_dedupe(unsupported_names),
        missing_evidence=not has_evidence_line(answer),
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def format_evidence_footer(
    language: str,
    tables: list[str],
    query_count: int,
    row_count: int,
) -> str:
    tables_text = ", ".join(tables) if tables else "deals_enriched"
    if language == UZ:
        return (
            f"🔎 Asos: DuckDB, jadvallar: {tables_text}; "
            f"SQL so‘rovlar: {query_count}; qatorlar: {row_count}."
        )
    return (
        f"🔎 Основание: DuckDB, таблицы: {tables_text}; "
        f"SQL-запросов: {query_count}; строк: {row_count}."
    )


def correction_prompt(
    language: str,
    unsupported_numbers: list[str],
    unsupported_names: list[str],
) -> str:
    pieces: list[str] = [
        "Your draft failed the deterministic verification step.",
    ]
    if unsupported_numbers:
        pieces.append("These numbers/dates/codes are not present in any tool result from this turn: "
                      + ", ".join(unsupported_numbers) + ".")
    if unsupported_names:
        pieces.append("These company/broker names are not present in any tool result from this turn: "
                      + ", ".join(unsupported_names) + ".")
    pieces.append(
        "Re-run the necessary tools (SQL, product search, company search, USD rate) and use only exact "
        "values returned by the tools. Do not calculate in your head, do not round unless the SQL did it, "
        "and do not use outside knowledge. Remove or correct every unsupported value."
    )
    pieces.append(
        "If the data cannot confirm the answer, reply with exactly this sentence and nothing else: "
        f"{no_answer(language)}"
    )
    return " ".join(pieces)
