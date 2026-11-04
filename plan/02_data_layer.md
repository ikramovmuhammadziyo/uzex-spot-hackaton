# 02 — Data Layer

## Files in workspace
| File | Rows | Contents |
|---|---|---|
| `deals_2022.csv` … `deals_2026.csv` | 500,000 | Deals by year |
| `contracts.csv` | 6,616 | Contract cards (product, attributes, currency, terms, seller) |
| `participants.csv` | 14,392 | Companies (sellers & buyers) |
| `brokers.csv` | 120 | Broker offices |
| `usd_rates.csv` | 1,766 | Daily USD→UZS rate |

## Parsing pitfalls (verified by inspection)
1. **Thousands separators**: `131 895 492` — spaces inside numbers, sometimes inside quoted fields. Must strip spaces before casting to numeric.
2. **Quoted commas**: company names/addresses contain commas → proper CSV parsing only (never naive split).
3. **Dates**: `ДД.ММ.ГГГГ` strings → cast to DATE.
4. **Time**: `HH:MM:SS` Tashkent.
5. **Empty fields**: `Дата оплаты`, `Дата поставки`, `Поставлено` may be empty → NULL.
6. **INN**: 9-digit strings — keep as TEXT (leading-zero safety, joins).
7. **Inconsistent product naming**: same product written differently by sellers («1 сорт» / «1-сорта», case differences, with/without field labels). Use normalized search (LOWER + LIKE / full-text) and contract attributes.

## Target schema (DuckDB)

### deals (union of 5 files)
```sql
deal_no        INTEGER   -- Номер сделки (gaps exist)
deal_date      DATE      -- Дата сделки
deal_time      TIME      -- Время сделки
auction_type   TEXT      -- Английский | Обратный | Двусторонний аукцион
quantity       INTEGER   -- Количество (лоты)
deal_sum       DOUBLE    -- Сумма сделки (в валюте контракта)
start_price    DOUBLE    -- Стартовая цена за единицу
contract_no    INTEGER   -- → contracts.contract_no
product_name   TEXT      -- Наименование товара (как в реестре)
lot            DOUBLE    -- Лот
unit           TEXT      -- Единица измерения
region         TEXT      -- Регион склада продавца
contract_type  TEXT      -- Внутренний | Экспортный
contract_form  TEXT      -- Спот | Форвард | Фьючерс
deal_state     TEXT      -- см. состояния ниже
seller_inn     TEXT      -- → participants.inn
buyer_inn      TEXT      -- → participants.inn
seller_broker  TEXT      -- → brokers.code
buyer_broker   TEXT      -- → brokers.code
payment_date   DATE NULL
delivery_date  DATE NULL
delivered      DOUBLE NULL  -- Поставлено (лоты)
```

### contracts
contract_no, product_name, brand, size, grade, type, class, tnved_code,
product_group, product_category, industry, unit, lot, currency (UZS|USD),
base_price, deposit_pct, delivery_basis, region, warehouse_address,
auction_type, contract_type, contract_form, payment_days, delivery_days,
packaging, seller_inn, reg_date, valid_until

### participants
inn, name, region, activity, role (Продавец|Покупатель), vat_payer

### brokers
code, name, inn, region

### usd_rates
date, rate

## Computed columns (view `deals_enriched`)
```sql
volume        = quantity * lot                       -- объём в единицах
unit_price    = deal_sum / (quantity * lot)          -- цена за единицу
currency      = contracts.currency                   -- через JOIN
sum_uzs       = CASE WHEN currency='USD'
                     THEN deal_sum * usd_rate_on_deal_date
                     ELSE deal_sum END
seller_name / buyer_name / broker names              -- через JOINs
```

## Deal states (business meaning)
| State | Meaning | Counting rule |
|---|---|---|
| Новый | concluded on last day (30.10.2026) | active |
| Не подписан | not signed | not a real deal |
| Заключен | forward/futures signed, payment pending | active |
| Ждёт оплату | spot signed, payment pending | active |
| Оплачен | paid, not delivered | active |
| Исполнен | fully executed | **completed** |
| Исполнен(Частично) | partially delivered (see Поставлено) | completed (partial) |
| Аннулирован(Не оплачен) | not paid on time → cancelled | **deal did NOT happen** |

> Rule of thumb: for "executed/completed" questions filter Исполнен (+Частично);
> for "concluded turnover" include active states; always exclude Аннулирован unless asked.
> When ambiguous, state the assumption in the answer.

## Implementation steps
1. `scripts/load_data.py` — pandas/DuckDB ingest with cleaning, output `uzex.duckdb`.
2. Validate: row counts per year must equal README (84,299 / 93,985 / 106,647 / 115,763 / 99,306 = 500,000).
3. Create `deals_enriched` view with joins + computed fields.
4. Sanity queries: min/max dates, distinct currencies, states distribution, INN join coverage.
