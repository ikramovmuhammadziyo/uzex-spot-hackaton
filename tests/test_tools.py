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


async def test_region_audit_distinguishes_joins_from_label_equality(runner):
    payload = json.loads(await runner.run('region_audit', {
        'start_date': '2024-01-01', 'end_date': '2024-12-31', 'basis': 'all'}))
    assert payload['ok']
    row = payload['rows'][0]
    assert row['total_rows'] == row['joined_contract_rows'] == 106647
    assert row['contract_key_join_pct'] == 100
    assert row['contract_label_equal_pct'] == 0
    assert row['seller_label_equal_pct'] == 100


async def test_registry_audit_computes_full_integrity_in_one_result(runner):
    payload = json.loads(await runner.run('registry_audit', {}))
    assert payload['ok'], payload
    row = payload['rows'][0]
    assert row['deals_count'] == 500000
    assert row['deal_number_gaps'] == 4956
    assert row['contracts_used'] == 6483
    assert row['unused_contracts_uzs'] == 127
    assert row['unused_contracts_usd'] == 6
    assert row['participants_trading'] == 14389
    assert row['brokers_never_seller'] == 4
    assert row['missing_rate_calendar_days'] == row['orphan_deals'] == row['deals_without_rate'] == 0
    assert row['rate_down_days'] == 822
    assert row['trading_days'] == 1236


async def test_mass_ranking_normalizes_largest_remaining_mass(runner):
    payload = json.loads(await runner.run('mass_ranking', {
        'start_date': '2022-01-03', 'end_date': '2026-10-30', 'basis': 'noncancelled',
        'measure': 'remaining', 'grouping': 'deal', 'states': ['Исполнен(Частично)'], 'limit': 1}))
    assert payload['ok'], payload
    assert payload['rows'][0]['deal_no'] == 167663
    assert float(payload['rows'][0]['tonnes']) == 2980
