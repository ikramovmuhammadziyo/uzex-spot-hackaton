"""Load the supplied UTF-8 CSV registry into an analytics-ready DuckDB file.

Usage: python scripts/load_data.py [--data-dir .] [--output data/uzex.duckdb]
Requires: pip install duckdb
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_DEALS = {2022: 84299, 2023: 93985, 2024: 106647, 2025: 115763, 2026: 99306}


def load_csv(con: duckdb.DuckDBPyConnection, path: Path, insert_sql: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    # All columns start as text: DuckDB's type inference would otherwise turn
    # nine-digit INNs into integers and vary types across the yearly files.
    query = insert_sql.replace(
        "FROM source_csv",
        "FROM read_csv(?, header=true, all_varchar=true, sample_size=-1)",
    )
    con.execute(query, [str(path)])


def check(con: duckdb.DuckDBPyConnection, sql: str, label: str) -> None:
    count = con.execute(sql).fetchone()[0]
    if count:
        raise ValueError(f"{label}: {count} bad rows")


def build(con: duckdb.DuckDBPyConnection, data_dir: Path) -> None:
    con.execute("""
        CREATE TABLE participants (
            inn VARCHAR PRIMARY KEY, name VARCHAR, region VARCHAR,
            activity VARCHAR, role VARCHAR, vat_payer VARCHAR
        );
        CREATE TABLE brokers (
            code VARCHAR PRIMARY KEY, name VARCHAR, inn VARCHAR, region VARCHAR
        );
        CREATE TABLE contracts (
            contract_no BIGINT PRIMARY KEY, product_name VARCHAR, brand VARCHAR,
            size VARCHAR, grade VARCHAR, "type" VARCHAR, "class" VARCHAR,
            tnved_code VARCHAR, product_group VARCHAR, product_category VARCHAR,
            industry VARCHAR, unit VARCHAR, lot DECIMAL(20,6), currency VARCHAR,
            currency_raw VARCHAR, base_price DECIMAL(28,6), deposit_pct DECIMAL(10,4),
            delivery_basis VARCHAR, region VARCHAR, warehouse_address VARCHAR,
            auction_type VARCHAR, contract_type VARCHAR, contract_form VARCHAR,
            payment_days INTEGER, delivery_days INTEGER, packaging VARCHAR,
            seller_inn VARCHAR, reg_date DATE, valid_until DATE
        );
        CREATE TABLE usd_rates (date DATE PRIMARY KEY, rate DECIMAL(18,6));
        CREATE TABLE deals (
            deal_no BIGINT PRIMARY KEY, deal_date DATE, deal_time TIME,
            auction_type VARCHAR, quantity BIGINT, deal_sum DECIMAL(28,6),
            start_price DECIMAL(28,6), contract_no BIGINT, product_name VARCHAR,
            lot DECIMAL(20,6), unit VARCHAR, region VARCHAR,
            contract_type VARCHAR, contract_form VARCHAR, deal_state VARCHAR,
            seller_inn VARCHAR, buyer_inn VARCHAR, seller_broker VARCHAR,
            buyer_broker VARCHAR, payment_date DATE, delivery_date DATE,
            delivered DECIMAL(20,6)
        );
    """)

    load_csv(con, data_dir / "participants.csv", """
        INSERT INTO participants SELECT "ИНН", "Наименование", "Регион",
            "Вид деятельности", "Роль", "Плательщик НДС" FROM source_csv
    """)
    load_csv(con, data_dir / "brokers.csv", """
        INSERT INTO brokers SELECT "Код брокера", "Наименование", "ИНН", "Регион"
        FROM source_csv
    """)
    load_csv(con, data_dir / "contracts.csv", """
        INSERT INTO contracts SELECT
            CAST("Номер контракта" AS BIGINT), "Наименование продукта",
            "Марка товара", "Размер товара", "Сорт товара", "Тип товара",
            "Класс товара", "Код ТН ВЭД", "Группа товара", "Категория товара",
            "Отрасль промышленности", "Единица измерения",
            CAST(REPLACE("Лот", ' ', '') AS DECIMAL(20,6)),
            CASE "Валюта" WHEN 'Узбекский сум' THEN 'UZS'
                WHEN 'Доллар США' THEN 'USD' ELSE NULL END,
            "Валюта",
            CAST(REPLACE("Базисная цена", ' ', '') AS DECIMAL(28,6)),
            CAST(NULLIF(REPLACE(REPLACE("Сумма залога", ' %', ''), ' ', ''), '') AS DECIMAL(10,4)),
            "Базис поставки", "Регион", "Адрес склада", "Тип торгов",
            "Тип контракта", "Форма контракта",
            CAST("Срок оплаты" AS INTEGER), CAST("Срок поставки" AS INTEGER),
            "Упаковка", "ИНН продавца",
            CAST(STRPTIME("Дата регистрации", '%d.%m.%Y') AS DATE),
            CAST(STRPTIME("Действует до", '%d.%m.%Y') AS DATE)
        FROM source_csv
    """)
    load_csv(con, data_dir / "usd_rates.csv", """
        INSERT INTO usd_rates SELECT
            CAST(STRPTIME("Дата", '%d.%m.%Y') AS DATE),
            CAST(REPLACE("Курс", ' ', '') AS DECIMAL(18,6))
        FROM source_csv
    """)
    for year, expected in EXPECTED_DEALS.items():
        load_csv(con, data_dir / f"deals_{year}.csv", """
            INSERT INTO deals SELECT
                CAST("Номер сделки" AS BIGINT),
                CAST(STRPTIME("Дата сделки", '%d.%m.%Y') AS DATE),
                CAST("Время сделки" AS TIME), "Тип торгов",
                CAST(REPLACE("Количество", ' ', '') AS BIGINT),
                CAST(REPLACE("Сумма сделки", ' ', '') AS DECIMAL(28,6)),
                CAST(REPLACE("Стартовая цена", ' ', '') AS DECIMAL(28,6)),
                CAST("Номер контракта" AS BIGINT), "Наименование товара",
                CAST(REPLACE("Лот", ' ', '') AS DECIMAL(20,6)),
                "Единица измерения", "Регион", "Тип контракта",
                "Форма контракта", "Состояние сделки", "ИНН продавца",
                "ИНН покупателя", "Брокер продавца", "Брокер покупателя",
                CAST(STRPTIME(NULLIF("Дата оплаты", ''), '%d.%m.%Y') AS DATE),
                CAST(STRPTIME(NULLIF("Дата поставки", ''), '%d.%m.%Y') AS DATE),
                CAST(NULLIF(REPLACE("Поставлено", ' ', ''), '') AS DECIMAL(20,6))
            FROM source_csv
        """)
        actual = con.execute("SELECT COUNT(*) FROM deals WHERE YEAR(deal_date)=?", [year]).fetchone()[0]
        if actual != expected:
            raise ValueError(f"deals_{year}: expected {expected}, got {actual}")
        print(f"deals_{year}: {actual:,}")

    con.execute("""
        CREATE VIEW deals_enriched AS SELECT
            d.*, c.currency, c.currency_raw, c.product_group,
            c.product_category, c.industry, c.tnved_code,
            sp.name AS seller_name, bp.name AS buyer_name,
            sb.name AS seller_broker_name, bb.name AS buyer_broker_name,
            r.rate AS usd_rate,
            d.quantity * d.lot AS volume,
            CASE WHEN d.quantity * d.lot <> 0
                THEN d.deal_sum / (d.quantity * d.lot) END AS unit_price,
            CASE WHEN c.currency = 'USD'
                THEN CAST(d.deal_sum * r.rate AS DECIMAL(38,6))
                WHEN c.currency = 'UZS' THEN CAST(d.deal_sum AS DECIMAL(38,6))
                END AS sum_uzs
        FROM deals d
        LEFT JOIN contracts c ON d.contract_no = c.contract_no
        LEFT JOIN participants sp ON d.seller_inn = sp.inn
        LEFT JOIN participants bp ON d.buyer_inn = bp.inn
        LEFT JOIN brokers sb ON d.seller_broker = sb.code
        LEFT JOIN brokers bb ON d.buyer_broker = bb.code
        LEFT JOIN usd_rates r ON d.deal_date = r.date
    """)

    counts = {table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
              for table in ("deals", "contracts", "participants", "brokers", "usd_rates", "deals_enriched")}
    expected_counts = {"deals": 500000, "contracts": 6616, "participants": 14392,
                       "brokers": 120, "usd_rates": 1765, "deals_enriched": 500000}
    if counts != expected_counts:
        raise ValueError(f"Unexpected table counts: {counts}")
    check(con, "SELECT COUNT(*) FROM contracts WHERE currency IS NULL", "unknown contract currency")
    check(con, "SELECT COUNT(*) FROM deals_enriched WHERE currency IS NULL OR seller_name IS NULL OR buyer_name IS NULL OR seller_broker_name IS NULL OR buyer_broker_name IS NULL OR usd_rate IS NULL OR sum_uzs IS NULL", "unmatched deal references")
    check(con, "SELECT COUNT(*) FROM deals WHERE quantity <= 0 OR lot <= 0 OR deal_sum < 0", "invalid deal amount/volume")
    print("validated:", counts)
    print("date range:", con.execute("SELECT MIN(deal_date), MAX(deal_date) FROM deals").fetchone())
    print("currencies:", con.execute("SELECT currency, COUNT(*) FROM contracts GROUP BY 1 ORDER BY 1").fetchall())
    print("states:", con.execute("SELECT deal_state, COUNT(*) FROM deals GROUP BY 1 ORDER BY 1").fetchall())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "uzex.duckdb")
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".building")
    temporary.unlink(missing_ok=True)
    try:
        con = duckdb.connect(str(temporary))
        try:
            build(con, args.data_dir.resolve())
            con.execute("CHECKPOINT")
        finally:
            con.close()
        os.replace(temporary, output)
        print("database:", output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    main()
