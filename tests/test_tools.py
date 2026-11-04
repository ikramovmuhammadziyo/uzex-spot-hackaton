from __future__ import annotations

import json

import pytest

from services.database import Database
from services.tools import ToolError, ToolRunner, validate_readonly_sql
from data import config


@pytest.fixture(scope="module")
def database():
    if not config.DB_PATH.is_file():
        pytest.skip(f"DuckDB file not found: {config.DB_PATH}")
    db = Database(config.DB_PATH)
    db.connect()
    yield db
    db.close()


@pytest.fixture(scope="module")
def runner(database):
    return ToolRunner(database)


def test_accepts_select_and_with() -> None:
    assert validate_readonly_sql("SELECT 1")
    assert validate_readonly_sql("WITH x AS (SELECT 1 AS n) SELECT n FROM x")
    assert validate_readonly_sql("SELECT replace('a b', ' ', '') AS x")


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM deals",
        "SELECT 1; DROP TABLE deals",
        "SELECT * FROM read_csv('deals.csv')",
        "SELECT * FROM 'deals.csv'",
        "PRAGMA database_list",
        "ATTACH 'other.db'",
        "SELECT * FROM query('SELECT 1')",
    ],
)
def test_rejects_unsafe_sql(sql: str) -> None:
    with pytest.raises(ToolError):
        validate_readonly_sql(sql)


async def test_run_sql_returns_rows(runner) -> None:
    payload = json.loads(
        await runner.run("run_sql", {"query": "SELECT COUNT(*) AS n FROM deals"})
    )
    assert payload["ok"] is True
    assert payload["rows"][0]["n"] == 500000
    assert payload["row_count"] == 1


async def test_run_sql_rejects_write(runner) -> None:
    payload = json.loads(await runner.run("run_sql", {"query": "DELETE FROM deals"}))
    assert payload["ok"] is False
    assert "SELECT" in payload["error"]


async def test_search_products(runner) -> None:
    payload = json.loads(await runner.run("search_products", {"term": "хлоп"}))
    assert payload["ok"] is True
    assert payload["matches"], payload
    assert any("хлоп" in str(item["product_name"]).lower() for item in payload["matches"])


async def test_search_products_word_order(runner) -> None:
    payload = json.loads(await runner.run("search_products", {"term": "каустическая сода"}))
    assert payload["ok"] is True
    names = {str(item["product_name"]) for item in payload["matches"]}
    assert "Сода каустическая" in names or "СОДА КАУСТИЧЕСКАЯ" in names, names


async def test_search_products_grade_variant(runner) -> None:
    payload = json.loads(await runner.run("search_products", {"term": "1-сорта"}))
    assert payload["ok"] is True
    assert payload["matches"], payload
    names = " ".join(str(item["product_name"]).lower() for item in payload["matches"])
    assert "1 сорт" in names or "1-сорт" in names


async def test_search_company_apostrophe_insensitive(runner) -> None:
    payload = json.loads(
        await runner.run("search_company", {"name_or_inn": "Mo'jotat Klaster"})
    )
    assert payload["ok"] is True
    assert payload["matches"], payload
    assert any(item["inn"] == "937937230" for item in payload["matches"])


async def test_search_company_unknown_name(runner) -> None:
    payload = json.loads(
        await runner.run("search_company", {"name_or_inn": "Узавтосаноат"})
    )
    assert payload["ok"] is True
    assert payload["matches"] == []
    assert payload["note"]


async def test_search_company_by_inn(runner) -> None:
    payload = json.loads(await runner.run("search_company", {"name_or_inn": "915688255"}))
    assert payload["ok"] is True
    assert payload["matches"]
    assert payload["matches"][0]["inn"] == "915688255"


async def test_usd_rate_exact(runner) -> None:
    payload = json.loads(await runner.run("usd_rate", {"date": "01.01.2022"}))
    assert payload["ok"] is True and payload["found"] is True
    assert str(payload["rate"]).startswith("10829.1")


async def test_usd_rate_out_of_range(runner) -> None:
    payload = json.loads(await runner.run("usd_rate", {"date": "15.06.2030"}))
    assert payload["ok"] is True and payload["found"] is False
    assert "available_range" in payload
