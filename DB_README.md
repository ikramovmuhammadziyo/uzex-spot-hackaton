# Database layer

Build the local DuckDB file from the provided UTF-8 CSVs:

```bash
python -m pip install duckdb
python utils/db_api/load_data.py
```

The script writes `data/uzex.duckdb` only after all imports and checks pass. It prints per-year counts, table counts, date range, currencies, and deal-state distribution. The database file is generated locally and should not be committed.

The actual `usd_rates.csv` has 1,765 rows (1 January 2022 through 31 October 2026). This corrects the original plan's count of 1,766.

Source checks completed: all five yearly deal files match the README row counts. All 500,000 deal rows reference an existing contract, seller, buyer, seller broker, buyer broker, and deal-date USD rate. Primary keys in the reference CSVs are unique.

## Query contract for the bot and query engine

Tables: `deals`, `contracts`, `participants`, `brokers`, `usd_rates`. English snake-case column names match `plan/02_data_layer.md`. `contracts.currency` is `UZS` or `USD`; the source label is preserved in `contracts.currency_raw`. INNs and TN VED codes are text.

`deals_enriched` joins contract, seller, buyer, both brokers and the rate on the deal date. It exposes all `deals` columns plus `currency`, `currency_raw`, `product_group`, `product_category`, `industry`, `tnved_code`, `seller_name`, `buyer_name`, `seller_broker_name`, `buyer_broker_name`, `usd_rate`, `volume`, `unit_price`, and `sum_uzs`.

`volume = quantity * lot` in the deal's unit. `unit_price = deal_sum / volume` in the contract currency. `sum_uzs` converts USD at the deal-date rate. Monetary source fields use `DECIMAL(28,6)` to avoid binary floating point rounding. `deposit_pct` stores the number before `%` (for example, `10 %` becomes `10`). Empty dates and `delivered` values are SQL `NULL`. `delivered` counts lots, so delivered volume is `delivered * lot`.

Python query results contain `datetime.date` and `decimal.Decimal` values. Convert these to ISO date strings and decimal strings before serializing tool responses to JSON; avoid casting money to binary floats.

The view includes every recorded deal state. For turnover or completed-deal questions, apply an explicit state filter and describe it in the answer. The CSVs are a snapshot as of 30 October 2026.

Example:

```sql
SELECT deal_no, deal_date, seller_name, buyer_name, currency, deal_sum, sum_uzs
FROM deals_enriched
WHERE deal_no = 185158;
```
