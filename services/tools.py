"""Tools exposed to the LLM.

The model never answers from memory: it calls these functions and gets JSON
back.  ``run_sql`` is deliberately conservative — only a single read-only
``SELECT``/``WITH`` statement, no file access, no DuckDB pragmas, and at most
100 returned rows.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from data import config

from .database import Database, DatabaseError
from .language import normalize

logger = logging.getLogger(__name__)

MAX_ROWS = config.SQL_MAX_ROWS

FORBIDDEN_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create",
    "truncate", "attach", "detach", "copy", "export", "import", "install",
    "load", "pragma", "call", "set", "reset", "vacuum", "checkpoint",
    "begin", "commit", "rollback", "grant", "revoke", "use", "merge",
    "upsert", "into", "transaction",
}

FORBIDDEN_FUNCTIONS = {
    "read_csv", "read_csv_auto", "read_parquet", "read_json", "read_json_auto",
    "read_text", "read_blob", "parquet_scan", "csv_scan", "json_scan",
    "sqlite_scan", "postgres_scan", "mysql_scan", "iceberg_scan", "delta_scan",
    "glob", "getenv", "current_setting", "load_extension", "query",
    "query_table", "read_xlsx", "st_read",
}


class ToolError(ValueError):
    """A tool argument/query problem that can be returned to the model."""


def _mask_sql_literals(sql: str) -> str:
    """Replace string literals, quoted identifiers and comments with spaces.

    The result has the same length as the input, so positions remain valid for
    masking dates/codes in a second pass.  Semicolons inside strings or
    comments therefore do not look like statement separators.
    """

    output: list[str] = []
    index = 0
    length = len(sql)
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False

    while index < length:
        char = sql[index]
        following = sql[index + 1] if index + 1 < length else ""

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
                output.append("\n")
            else:
                output.append(" ")
            index += 1
            continue

        if in_block_comment:
            if char == "*" and following == "/":
                output.extend((" ", " "))
                index += 2
                in_block_comment = False
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
            continue

        if in_single:
            if char == "'":
                if following == "'":
                    output.extend((" ", " "))
                    index += 2
                    continue
                in_single = False
            output.append("\n" if char == "\n" else " ")
            index += 1
            continue

        if in_double:
            if char == '"':
                if following == '"':
                    output.extend((" ", " "))
                    index += 2
                    continue
                in_double = False
            output.append("\n" if char == "\n" else " ")
            index += 1
            continue

        if char == "-" and following == "-":
            in_line_comment = True
            output.extend((" ", " "))
            index += 2
            continue
        if char == "/" and following == "*":
            in_block_comment = True
            output.extend((" ", " "))
            index += 2
            continue
        if char == "'":
            in_single = True
            output.append(" ")
            index += 1
            continue
        if char == '"':
            in_double = True
            output.append(" ")
            index += 1
            continue

        output.append(char)
        index += 1

    return "".join(output)


def validate_readonly_sql(sql: str) -> str:
    """Validate a single read-only statement and return it without trailing ';'."""

    if not isinstance(sql, str):
        raise ToolError("query must be a string")
    statement = sql.strip()
    if not statement:
        raise ToolError("query is empty")
    if len(statement) > 20_000:
        raise ToolError("query is too long")

    masked = _mask_sql_literals(statement)
    if not re.match(r"(?is)^(select|with)\b", masked):
        raise ToolError("only a single read-only SELECT or WITH query is allowed")

    if ";" in masked:
        parts = masked.split(";")
        if any(part.strip() for part in parts[1:]):
            raise ToolError("multiple SQL statements are not allowed")
        statement = statement[: masked.index(";")].rstrip()

    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", masked, re.IGNORECASE):
            raise ToolError(f"SQL keyword '{keyword.upper()}' is not allowed")

    for function in FORBIDDEN_FUNCTIONS:
        if re.search(rf"\b{function}\s*\(", masked, re.IGNORECASE):
            raise ToolError(f"SQL function '{function}' is not allowed")

    # Block replacement scans such as FROM 'deals.csv'.
    if re.search(r"(?is)\b(?:from|join)\s*'", statement):
        raise ToolError("reading files from SQL is not allowed")

    return statement


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=_json_default)


def _rows_as_dicts(columns: list[str], rows: list[list[Any]]) -> list[dict[str, Any]]:
    return [dict(zip(columns, row)) for row in rows]


class ToolRunner:
    def __init__(self, database: Database, max_rows: int = MAX_ROWS) -> None:
        self.database = database
        self.max_rows = max_rows

    async def run(self, name: str, arguments: dict[str, Any] | None) -> str:
        arguments = arguments or {}
        try:
            if name == "run_sql":
                payload = await self._run_sql(arguments)
            elif name == "search_products":
                payload = await self._search_products(arguments)
            elif name == "search_company":
                payload = await self._search_company(arguments)
            elif name == "usd_rate":
                payload = await self._usd_rate(arguments)
            else:
                raise ToolError(f"unknown tool: {name}")
        except ToolError as exc:
            payload = {"ok": False, "tool": name, "error": str(exc)}
        except DatabaseError as exc:
            payload = {"ok": False, "tool": name, "error": f"database error: {exc}"}
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("tool %s failed", name)
            payload = {"ok": False, "tool": name, "error": f"internal tool error: {exc}"}
        return _dumps(payload)

    # ------------------------------------------------------------------
    # run_sql
    # ------------------------------------------------------------------
    async def _run_sql(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = arguments.get("query", "")
        statement = validate_readonly_sql(query)
        result = await self.database.query(statement, max_rows=self.max_rows)
        payload: dict[str, Any] = {
            "ok": True,
            "tool": "run_sql",
            "columns": result.columns,
            "rows": _rows_as_dicts(result.columns, result.rows),
            "row_count": result.row_count,
            "truncated": result.truncated,
        }
        if result.truncated:
            payload["note"] = (
                f"Only the first {self.max_rows} rows are shown. "
                "Aggregate in SQL (COUNT/SUM/AVG/GROUP BY) instead of selecting raw rows."
            )
        return payload

    # ------------------------------------------------------------------
    # search_products
    # ------------------------------------------------------------------
    async def _search_products(self, arguments: dict[str, Any]) -> dict[str, Any]:
        term = str(arguments.get("term", "")).strip()
        if not term:
            raise ToolError("term is required")
        if len(term) > 200:
            raise ToolError("term is too long")

        variants = _search_variants(term)
        matches = await self._product_matches(variants)
        note = None
        if not matches:
            tokens = [
                _compact_text(part)
                for part in re.split(r"[^\w]+", normalize(term), flags=re.UNICODE)
                if len(part) >= 3
            ]
            tokens = [token for token in tokens if token][:5]
            if tokens:
                matches = await self._product_matches_by_tokens(tokens)
                if matches:
                    note = "The exact phrase was not found; matched these individual words."
        if not matches:
            note = "No products in the registry matched this term."
        return {
            "ok": True,
            "tool": "search_products",
            "term": term,
            "matches": matches,
            "note": note,
        }

    async def _product_matches(self, variants: set[str]) -> list[dict[str, Any]]:
        patterns = [f"%{variant}%" for variant in variants]
        if not patterns:
            return []

        contract_conditions = " OR ".join(
            f"{_compact_sql(column)} LIKE ?"
            for column in ("product_name", "brand", "size", "grade", '"type"', '"class"')
        )
        params: list[Any] = []
        for pattern in patterns:
            params.extend([pattern] * 6)

        contract_sql = f"""
            SELECT product_name,
                   coalesce(brand, '') AS brand,
                   coalesce(size, '') AS size,
                   coalesce(grade, '') AS grade,
                   coalesce("type", '') AS type,
                   coalesce("class", '') AS class,
                   unit,
                   currency,
                   COUNT(*) AS contract_count
            FROM contracts
            WHERE {contract_conditions}
            GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
            ORDER BY contract_count DESC, product_name
            LIMIT 20
        """
        contract_rows = await self.database.query(contract_sql, params, max_rows=20)

        deal_params: list[Any] = []
        deal_conditions = []
        for pattern in patterns:
            deal_conditions.append(f"{_compact_sql('product_name')} LIKE ?")
            deal_params.append(pattern)
        deal_sql = f"""
            SELECT product_name, COUNT(*) AS deal_count
            FROM deals
            WHERE {' OR '.join(deal_conditions)}
            GROUP BY 1
            ORDER BY deal_count DESC, product_name
            LIMIT 20
        """
        deal_rows = await self.database.query(deal_sql, deal_params, max_rows=20)

        merged: dict[str, dict[str, Any]] = {}
        for row in contract_rows.rows:
            item = dict(zip(contract_rows.columns, row))
            name = str(item["product_name"])
            merged[name] = {
                "product_name": name,
                "brand": item["brand"],
                "size": item["size"],
                "grade": item["grade"],
                "type": item["type"],
                "class": item["class"],
                "unit": item["unit"],
                "currency": item["currency"],
                "contract_count": item["contract_count"],
                "deal_count": 0,
            }
        for row in deal_rows.rows:
            item = dict(zip(deal_rows.columns, row))
            name = str(item["product_name"])
            merged.setdefault(
                name,
                {
                    "product_name": name,
                    "brand": "",
                    "size": "",
                    "grade": "",
                    "type": "",
                    "class": "",
                    "unit": None,
                    "currency": None,
                    "contract_count": 0,
                    "deal_count": 0,
                },
            )
            merged[name]["deal_count"] = item["deal_count"]

        return sorted(
            merged.values(),
            key=lambda item: (int(item.get("deal_count") or 0), int(item.get("contract_count") or 0)),
            reverse=True,
        )[:20]

    async def _product_matches_by_tokens(self, tokens: list[str]) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        for token in tokens:
            pattern = f"%{token}%"
            conditions.append(
                f"({_compact_sql('product_name')} LIKE ? OR {_compact_sql('brand')} LIKE ? "
                f"OR {_compact_sql('grade')} LIKE ?)"
            )
            params.extend([pattern, pattern, pattern])

        sql = f"""
            SELECT product_name, coalesce(brand, '') AS brand, unit, currency,
                   COUNT(*) AS contract_count
            FROM contracts
            WHERE {' AND '.join(conditions)}
            GROUP BY 1, 2, 3, 4
            ORDER BY contract_count DESC, product_name
            LIMIT 20
        """
        result = await self.database.query(sql, params, max_rows=20)
        return [
            {
                "product_name": dict(zip(result.columns, row))["product_name"],
                "brand": dict(zip(result.columns, row))["brand"],
                "unit": dict(zip(result.columns, row))["unit"],
                "currency": dict(zip(result.columns, row))["currency"],
                "contract_count": dict(zip(result.columns, row))["contract_count"],
                "deal_count": 0,
            }
            for row in result.rows
        ]

    # ------------------------------------------------------------------
    # search_company
    # ------------------------------------------------------------------
    async def _search_company(self, arguments: dict[str, Any]) -> dict[str, Any]:
        term = str(arguments.get("name_or_inn", "")).strip()
        if not term:
            raise ToolError("name_or_inn is required")
        if len(term) > 200:
            raise ToolError("name_or_inn is too long")

        matches: list[dict[str, Any]] = []
        lowered = normalize(term)

        if re.fullmatch(r"\d{9}", term):
            result = await self.database.query(
                "SELECT inn, name, region, activity, role, vat_payer "
                "FROM participants WHERE inn = ? LIMIT 20",
                [term],
                max_rows=20,
            )
            matches.extend(_rows_as_dicts(result.columns, result.rows))
            broker = await self.database.query(
                "SELECT code, name, inn, region FROM brokers WHERE inn = ? LIMIT 20",
                [term],
                max_rows=20,
            )
            for row in _rows_as_dicts(broker.columns, broker.rows):
                row["role"] = "Брокер"
                matches.append(row)
        elif re.fullmatch(r"BK\d{3}", term, re.IGNORECASE):
            code = term.upper()
            broker = await self.database.query(
                "SELECT code, name, inn, region FROM brokers WHERE upper(code) = ? LIMIT 20",
                [code],
                max_rows=20,
            )
            for row in _rows_as_dicts(broker.columns, broker.rows):
                row["role"] = "Брокер"
                matches.append(row)
        else:
            compact = _compact_text(term)
            pattern = f"%{compact}%"
            participants = await self.database.query(
                f"SELECT inn, name, region, activity, role, vat_payer "
                f"FROM participants WHERE {_compact_sql('name')} LIKE ? "
                f"ORDER BY name LIMIT 20",
                [pattern],
                max_rows=20,
            )
            matches.extend(_rows_as_dicts(participants.columns, participants.rows))
            brokers = await self.database.query(
                f"SELECT code, name, inn, region FROM brokers "
                f"WHERE {_compact_sql('name')} LIKE ? OR {_compact_sql('code')} LIKE ? "
                f"ORDER BY name LIMIT 20",
                [pattern, pattern],
                max_rows=20,
            )
            for row in _rows_as_dicts(brokers.columns, brokers.rows):
                row["role"] = "Брокер"
                matches.append(row)

            if not matches:
                tokens = [
                    _compact_text(part)
                    for part in re.split(r"[^\w]+", lowered, flags=re.UNICODE)
                    if len(part) >= 3
                ]
                tokens = [token for token in tokens if token][:5]
                if tokens:
                    conditions = " AND ".join(
                        [f"{_compact_sql('name')} LIKE ?"] * len(tokens)
                    )
                    token_params = [f"%{token}%" for token in tokens]
                    participants = await self.database.query(
                        f"SELECT inn, name, region, activity, role, vat_payer "
                        f"FROM participants WHERE {conditions} ORDER BY name LIMIT 20",
                        token_params,
                        max_rows=20,
                    )
                    matches.extend(_rows_as_dicts(participants.columns, participants.rows))
                    brokers = await self.database.query(
                        f"SELECT code, name, inn, region FROM brokers "
                        f"WHERE {conditions} ORDER BY name LIMIT 20",
                        token_params,
                        max_rows=20,
                    )
                    for row in _rows_as_dicts(brokers.columns, brokers.rows):
                        row["role"] = "Брокер"
                        matches.append(row)

        return {
            "ok": True,
            "tool": "search_company",
            "term": term,
            "matches": matches[:30],
            "note": None if matches else "No company or broker matched this term.",
        }

    # ------------------------------------------------------------------
    # usd_rate
    # ------------------------------------------------------------------
    async def _usd_rate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw_date = str(arguments.get("date", "")).strip()
        parsed = _parse_date(raw_date)
        result = await self.database.query(
            "SELECT date, rate FROM usd_rates WHERE date = CAST(? AS DATE)",
            [parsed.isoformat()],
            max_rows=1,
        )
        if result.rows:
            item = dict(zip(result.columns, result.rows[0]))
            return {
                "ok": True,
                "tool": "usd_rate",
                "found": True,
                "date": item["date"],
                "rate": item["rate"],
                "unit": "UZS per 1 USD",
            }

        bounds = await self.database.query(
            "SELECT MIN(date), MAX(date) FROM usd_rates", max_rows=1
        )
        min_date, max_date = (bounds.rows[0] if bounds.rows else (None, None))
        return {
            "ok": True,
            "tool": "usd_rate",
            "found": False,
            "date": parsed.isoformat(),
            "available_range": [min_date, max_date],
            "note": "No exchange rate for this date. Do not guess or interpolate.",
        }


def _search_variants(term: str) -> set[str]:
    """Compact a term for punctuation/apostrophe-insensitive matching."""

    compact = _compact_text(term)
    if not compact:
        return set()
    return {compact, compact.replace("ё", "е")}


def _compact_text(value: str) -> str:
    return re.sub(r"[^a-zа-яё0-9]+", "", normalize(value).lower())


def _compact_sql(column: str) -> str:
    """SQL expression matching ``_compact_text`` on a column value."""

    return (
        f"regexp_replace(lower(coalesce({column}, '')), "
        "'[^a-zа-яё0-9]+', '', 'g')"
    )


def _parse_date(value: str) -> date:
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ToolError("date must be in DD.MM.YYYY or YYYY-MM-DD format")


# ---------------------------------------------------------------------------
# OpenAI tool schemas
# ---------------------------------------------------------------------------
TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": (
                "Execute one read-only SELECT/WITH query against DuckDB and return up to 100 rows. "
                "Use deals_enriched for deal analytics; it already contains currency, names, "
                "usd_rate, volume, unit_price and sum_uzs. Aggregate with SQL, never in your head. "
                "Non-SELECT statements and file access are rejected."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A single DuckDB SELECT or WITH query.",
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": (
                "Fuzzy-search product names in contracts and deals. Handles variants such as "
                "'1 сорт' vs '1-сорта' and returns distinct registry names with counts and attributes. "
                "Call this before filtering by product name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "term": {
                        "type": "string",
                        "description": "Product name or part of it, in Russian or Uzbek.",
                    }
                },
                "required": ["term"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_company",
            "description": (
                "Find a participant company by 9-digit INN or fuzzy name, or a broker by code (BK...) "
                "or name. Returns INN, name, region, role and activity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name_or_inn": {
                        "type": "string",
                        "description": "Company name, 9-digit INN, broker code (BK001) or broker name.",
                    }
                },
                "required": ["name_or_inn"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "usd_rate",
            "description": (
                "Return the official USD→UZS rate for one date from usd_rates. "
                "Date format: DD.MM.YYYY or YYYY-MM-DD. Returns found=false outside the data range."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date in DD.MM.YYYY or YYYY-MM-DD format.",
                    }
                },
                "required": ["date"],
                "additionalProperties": False,
            },
        },
    },
]
