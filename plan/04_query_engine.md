# 04 — Query Engine (LLM tools)

The LLM never answers from memory. It calls these tools; numbers come only from tool results.

## Tool 1: `run_sql(query: str) -> rows`
- Executes a **read-only SELECT** against DuckDB (`deals_enriched`, `contracts`, `participants`, `brokers`, `usd_rates`).
- Safety: reject non-SELECT; LIMIT 100 enforced; 10 s timeout.
- Returns JSON rows + row count.
- The schema + calculation rules are embedded in the system prompt.

## Tool 2: `search_products(term: str) -> list`
- Fuzzy search over `contracts.product_name` + attributes and `deals.product_name`.
- Case-insensitive, handles «1 сорт» vs «1-сорта» variants: normalize (lower, strip «Марка/Размер/Сорт/Тип/Класс» labels, collapse dashes/spaces).
- Returns distinct names + counts so the LLM can pick the right one.

## Tool 3: `search_company(name_or_inn: str) -> list`
- Finds participants by INN or fuzzy name; returns INN, name, region, role.
- Same for brokers by code/name.

## Tool 4: `usd_rate(date: str) -> float`
- Rate for a given date (helper so the LLM doesn't do currency joins by hand for simple asks).

## System prompt essentials
1. Full DB schema (tables, columns, RU names ↔ SQL names mapping).
2. Calculation rules: `volume = quantity*lot`, `unit_price = sum/(quantity*lot)`, USD→UZS via `usd_rates` on deal_date.
3. Deal-state semantics table (Исполнен vs Аннулирован, etc.).
4. "Thousands in sums use spaces in raw CSV — already cleaned, use plain numbers."
5. **Hard rules**:
   - Answer ONLY from tool results. No outside knowledge. No invented numbers.
   - If tools return nothing relevant → say explicitly the data has no answer (in the question's language).
   - Always include evidence: filters used + source identifiers (deal no., contract no., INN).
   - Answer in the language of the question (RU or UZ).
   - State assumptions when interpretation is ambiguous.

## Common query patterns (recipes to embed in prompt)
- **Top-N by turnover**: `SELECT seller_name, SUM(sum_uzs) … GROUP BY … ORDER BY … LIMIT N`
- **Biggest deal**: `ORDER BY deal_sum DESC` (mind currency — compare in UZS via `sum_uzs`).
- **Product price**: `unit_price` aggregates filtered by normalized product name.
- **Regional stats**: group by `region`.
- **Broker stats**: join brokers on `seller_broker`/`buyer_broker`.
- **Time trends**: `date_trunc('month', deal_date)`.
- **Cancellation rate**: `deal_state = 'Аннулирован(Не оплачен)'` share.
- **Export deals**: `contract_type = 'Экспортный'`, sums in USD; convert with rates when asked in UZS.
