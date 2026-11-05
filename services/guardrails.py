"""Deterministic post-generation checks.

The LLM is allowed to phrase an answer, but every number, date, INN, broker
code and company name in the substantive part of the answer must be traceable
to a tool result from the same conversation turn.  This module implements the
check without importing aiogram, DuckDB or any network library, which keeps it
easy to unit-test.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from datetime import date, timedelta

from .numeric import SCALES, decimal_value, money_scale_from_column, rounded_equal
from dataclasses import dataclass, field

from .language import UZ, normalize

NO_ANSWER_RU = "В данных реестра ответа на этот вопрос нет."
NO_ANSWER_UZ = "Maʼlumotlar reyestrida bu savolga javob yoʻq."


def no_answer(language: str) -> str:
    return NO_ANSWER_UZ if language == UZ else NO_ANSWER_RU


def is_no_answer(text: str) -> bool:
    value = normalize(text or "").strip().rstrip(".! ")
    return value in {normalize(NO_ANSWER_RU).rstrip(".! "),
                     normalize(NO_ANSWER_UZ).rstrip(".! ")}


def has_partial_refusal(text: str) -> bool:
    value = normalize(text)
    return not is_no_answer(text) and any(
        normalize(marker).rstrip(".") in value
        for marker in (NO_ANSWER_RU, NO_ANSWER_UZ)
    )


# ---------------------------------------------------------------------------
# Token extraction
# ---------------------------------------------------------------------------
DATE_ISO_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
DATE_DMY_RE = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)")
CODE_RE = re.compile(r"(?<![A-Za-z0-9])BK\d{3}(?![A-Za-z0-9])", re.IGNORECASE)
NUMBER_RE = re.compile(
    r"(?<![\w.,])"
    r"[+−-]?(?:\d{1,3}(?:[ \u00A0\u202F]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?![\w])"
)
GROUPED_NUMBER_RE = re.compile(
    r"(?<![\w.,])[+−-]?\d{1,3}(?:[., \u00A0\u202F]\d{3})+(?:[.,]\d+)?(?![\w])"
)


@dataclass(frozen=True, slots=True)
class Candidate:
    raw: str
    kind: str  # "number" | "date" | "code"
    variants: frozenset[str]
    scale: Decimal = Decimal(1)
    start: int = -1
    end: int = -1


def _date_candidate(year: int, month: int, day: int) -> Candidate | None:
    try:
        date(year, month, day)
    except ValueError:
        return None
    canonical = f"{year:04d}{month:02d}{day:02d}"
    return Candidate(
        raw=f"{day:02d}.{month:02d}.{year:04d}",
        kind="date",
        variants=frozenset({canonical}),
    )


def number_variants(raw: str) -> frozenset[str]:
    """Return one canonical decimal interpretation; never strip decimal separators."""

    try:
        return frozenset({str(decimal_value(raw).normalize())})
    except InvalidOperation:
        return frozenset()


def _candidate_from_number(raw: str, start: int, end: int) -> Candidate:
    return Candidate(raw=raw, kind="number", variants=number_variants(raw), start=start, end=end)


def _money_context(text: str, start: int, end: int) -> bool:
    if re.match(r"\s*(?:сум\b|UZS\b|USD\b|доллар)", text[end:], re.I):
        return True
    before = text[:start]
    lines = before.split("\n")
    column = lines[-1].count("|")
    if column:
        for line in reversed(lines[:-1]):
            if "|" not in line:
                break
            cells = line.split("|")
            if column < len(cells) and re.search(r"сум|UZS|USD", cells[column], re.I):
                return True
    return False


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
    for match in re.finditer(r"(?<![\d.])(\d{1,2})\.(\d{1,2})(?![\d.])", partially_masked):
        day, month = map(int, match.groups())
        before, after = text[:match.start()], text[match.end():]
        if not (1 <= day <= 31 and 1 <= month <= 12):
            continue
        if (re.search(r"[–—-]\s*$", before) or re.match(r"\s*[–—-]", after)
                or re.search(r"(?:период|дата|снимка|с|по|на|до|от|from|to)[: ]*\s*$", before, re.I)):
            candidates.append(Candidate(match.group(0), "date_fragment", frozenset({f"{month:02d}{day:02d}"})))
            mask(match.start(), match.end())

    partially_masked = "".join(remaining)
    for match in CODE_RE.finditer(partially_masked):
        candidates.append(
            Candidate(raw=match.group(0), kind="code", variants=frozenset({match.group(0).upper()}))
        )
        mask(match.start(), match.end())

    partially_masked = "".join(remaining)
    for match in GROUPED_NUMBER_RE.finditer(partially_masked):
        candidates.append(_candidate_from_number(match.group(0), match.start(), match.end()))
        mask(match.start(), match.end())

    partially_masked = "".join(remaining)
    for match in NUMBER_RE.finditer(partially_masked):
        candidates.append(_candidate_from_number(match.group(0), match.start(), match.end()))

    # Scale belongs to this number, never to arbitrary digits elsewhere.
    enriched = []
    for candidate in candidates:
        if candidate.kind != "number":
            enriched.append(candidate)
            continue
        tail = text[candidate.end:]
        scale_match = re.match(r"\s*(трлн|млрд|млн|тыс|trln|bn|mln)\b", tail, re.I)
        scale = SCALES[scale_match.group(1).lower()] if scale_match else Decimal(1)
        prefix = text[max(0, candidate.start-30):candidate.start]
        identifier = bool(re.search(r"(?:№|ИНН|STIR|deal_no\s*=|contract_no\s*=|inn\s*=)\s*$", prefix, re.I))
        identifier_kind = "inn" if re.search(r"(?:ИНН|STIR)\s*$", prefix, re.I) else "identifier"
        enriched.append(Candidate(candidate.raw, identifier_kind if identifier else "money"
                                  if _money_context(text, candidate.start, candidate.end) else "number",
                                  candidate.variants, scale, candidate.start, candidate.end))
    return enriched


def is_significant(candidate: Candidate) -> bool:
    """All extracted factual values matter, including small percentages and counts."""

    if candidate.kind in {"date", "code"}:
        return True
    return True


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
        self._numbers: set[Decimal] = set()
        self._exact_digits: set[str] = set()
        self.results: list[dict] = []
        self.requested_years: set[int] = set()
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
                self._variants.add(candidate.raw[3:5] + candidate.raw[:2])
                self._variants.add(str(Decimal(candidate.raw[-4:]).normalize()))
                self._numbers.add(Decimal(candidate.raw[-4:]))
            elif candidate.kind in {"number", "money", "code"}:
                if not numbers:
                    continue
            self._variants.update(candidate.variants)
            raw_digits = re.sub(r"[\s\u00a0\u202f]", "", candidate.raw)
            if numbers and raw_digits.isdigit():
                self._exact_digits.add(raw_digits)
            if candidate.kind in {"number", "money"}:
                try:
                    self._numbers.add(decimal_value(candidate.raw) * candidate.scale)
                except InvalidOperation:
                    pass

    def contains_number(self, candidate: Candidate) -> bool:
        if candidate.kind in {"identifier", "inn"}:
            digits = re.sub(r"\s", "", candidate.raw)
            return (candidate.kind != "inn" or len(digits) == 9) and digits in self._exact_digits
        if candidate.kind not in {"number", "money"}:
            return bool(candidate.variants & self._variants)
        try:
            shown = decimal_value(candidate.raw)
            return any(rounded_equal(source / candidate.scale, shown, allow_integer=candidate.kind == "money") for source in self._numbers)
        except InvalidOperation:
            return False

    def add_result(self, payload: dict) -> None:
        """Retain typed columns/rows and provenance; metadata is not factual evidence."""
        self.results.append(payload)
        import json
        for key in ("rows", "matches", "date", "rate", "available_range"):
            if key in payload:
                self.add(json.dumps(payload[key], ensure_ascii=False, default=str))
        for row in payload.get("rows", []):
            for column, value in row.items():
                if value is not None:
                    try:
                        self._numbers.add(decimal_value(str(value)))
                    except InvalidOperation:
                        pass
                # Explicit SQL aliases carry display scaling into evidence.
                scale = money_scale_from_column(column)
                if scale is not None and value is not None:
                    try:
                        self._numbers.add(decimal_value(str(value)) * scale)
                    except InvalidOperation:
                        pass

    def add_request(self, question: str) -> None:
        # User-supplied years identify the request; they are not query-derived facts.
        self.requested_years.update(int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", question))

    def add_query_scope(self, query: str) -> None:
        """Support calendar boundaries without treating them as observed extrema."""
        self.add(query, numbers=False, dates=True, names=False)
        for match in re.finditer(r"\bdeal_date\s*<\s*DATE\s*'([0-9-]+)'", query, re.I):
            try:
                self.add((date.fromisoformat(match.group(1))-timedelta(days=1)).isoformat(),
                         numbers=False, names=False)
            except ValueError:
                pass

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
    substantive = strip_evidence_lines(answer).replace("**", "").replace("`", "")
    # List ordinals are formatting, not registry facts.
    substantive = re.sub(r"(?m)^\s*\d+[.)]\s+", "", substantive)
    substantive = re.sub(r"(?<!\S)\d+\)(?=\s)", "", substantive)
    # Check identifiers in citations, but not generated query/row counters.
    citations = "\n".join(line for line in answer.splitlines()
                          if re.search(r"(?:deal_no|contract_no|ИНН|№|BK\d{3})", line, re.I)
                          and line not in substantive)
    check_text = substantive + "\n" + citations
    check_text = re.sub(r"(?m)^\s*\d+[.)]\s+", "", check_text)
    for candidate in extract_candidates(check_text):
        if not is_significant(candidate):
            continue
        if not evidence.contains_number(candidate):
            # Mathematical unit definitions are not measured registry facts.
            prefix = check_text[max(0, candidate.start - 80):candidate.start].lower()
            try:
                value = decimal_value(candidate.raw) if candidate.kind in {"number", "money"} else None
            except InvalidOperation:
                value = None
            conversion = value == 1000 and bool(re.search(
                r"(?:/|÷|(?:раз)?дел[а-я]*(?:\s+[^.!?;\n]{0,100})?\s+на)\s*$", prefix))
            percentage_multiplier = value == 100 and bool(re.search(r"[×*/÷]\s*$", prefix))
            rate_denominator = value == 1 and bool(re.search(r"(?:UZS|сум)\s+(?:за|per)\s*$", prefix, re.I))
            following = check_text[candidate.end:candidate.end + 15].lower()
            requested_year = (value in evidence.requested_years and candidate.kind == "number"
                              and bool(re.search(r"год|yil|year|период", prefix[-40:])
                                       or re.match(r"\s*[-–]?\s*(?:год|yil|year)", following)))
            if not (conversion or percentage_multiplier or rate_denominator or requested_year):
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
        "and do not use outside knowledge. Remove or correct every unsupported value. "
        "This is an internal draft: do not mention corrections or a previous answer to the user. "
        "Revise the complete JSON envelope, preserving coverage and all requested metric IDs. "
        "Every successful result from every round of this answer remains valid evidence; "
        "a later SQL query does not invalidate earlier results. Keep already supported sections "
        "and repair only unsupported claims. Do not label earlier results from this answer as "
        "a previous run or as provisional."
    )
    pieces.append(
        "Answer supported subquestions and identify unavailable subparts. A verification failure "
        "does not mean data is absent. Use a whole-answer refusal only for an entirely unsupported request: "
        f"{no_answer(language)}"
    )
    return " ".join(pieces)
