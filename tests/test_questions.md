# Ground-truth question bank

Generated from `data/uzex.duckdb` (500,000 deals, snapshot 30.10.2026).
Use this file for manual regression: ask the bot the RU and UZ variants, compare
the number/name, and check that the answer includes an evidence line.

> **State filter matters.** Most business questions below use
> `deal_state <> 'Аннулирован(Не оплачен)'` ("real deals"). Count questions show
> both the total and the cancelled part. The bot must state which filter it used.

**No-answer sentences (must be exact):**

- RU: `В данных реестра ответа на этот вопрос нет.`
- UZ: `Maʼlumotlar reyestrida bu savolga javob yoʻq.`

---

## A. Aggregates

### A1. Deals in 2024

- RU: Сколько всего сделок заключено в 2024 году?
- UZ: 2024-yilda jami nechta bitim tuzilgan?

```sql
SELECT COUNT(*) FROM deals
WHERE deal_date >= DATE '2024-01-01' AND deal_date < DATE '2025-01-01';
```

- Total: **106 647**
- Breakdown: Исполнен 94 481; Исполнен(Частично) 4 843; Аннулирован(Не оплачен) 7 323.
- Expected: 106 647, with the state breakdown and the note that 7 323 were cancelled.

### A2. Top seller in 2025

- RU: Какая компания продала на наибольшую сумму в 2025?
- UZ: 2025-yilda eng katta summaga sotgan kompaniya qaysi?

```sql
SELECT seller_inn, seller_name, SUM(sum_uzs) AS total
FROM deals_enriched
WHERE deal_date >= DATE '2025-01-01' AND deal_date < DATE '2026-01-01'
  AND deal_state <> 'Аннулирован(Не оплачен)'
GROUP BY 1, 2 ORDER BY total DESC LIMIT 1;
```

- Winner: **«Mo‘jotat Klaster» MChJ**, INN **937937230**
- Turnover excluding cancelled: **2 403 801 528 841.00 UZS** (2 059 deals)
- Including cancelled: 2 574 151 174 001.00 UZS
- Expected: the company name and INN; the amount is a bonus. State the filter.

### A3. Turnover in 2023

- RU: Общий объём торгов в сумах за 2023 год?
- UZ: 2023-yil uchun jami savdo hajmi so‘mda?

```sql
SELECT SUM(sum_uzs) AS total_uzs, COUNT(*) AS deals
FROM deals_enriched
WHERE deal_date >= DATE '2023-01-01' AND deal_date < DATE '2024-01-01'
  AND deal_state <> 'Аннулирован(Не оплачен)';
```

- Excluding cancelled: **34 187 428 452 052.38 UZS** (87 672 deals)
- Including all: 36 616 596 290 597.60 UZS (93 985 deals)
- Expected: the UZS total and a note that cancelled deals were excluded.

---

## B. Lookups

### B1. Deal №185158

- RU: Найди сделку №185158 — кто продавец и покупатель?
- UZ: 185158-raqamli bitimni top — sotuvchi va xaridor kim?

```sql
SELECT * FROM deals_enriched WHERE deal_no = 185158;
```

- Date: **02.01.2023**
- Product: Сода каустическая Тип твердая; 19 tonnes
- Amount: **131 895 492.00 UZS**; state: **Исполнен**
- Seller: **«Ko‘rak Kimyo» MChJ**, INN **986932945**
- Buyer: **«Chededum Logistik» MChJ**, INN **923911061**
- Seller broker: BK085 KAZEHI BROKER MCHJ; buyer broker: BK048 «ФЕРИ БРОКЕР» МЧЖ
- Expected: deal number, date, seller, buyer, amount/currency, state.

### B2. Company by INN

- RU: Что за компания с ИНН 986932945?
- UZ: STIR 986932945 qanday kompaniya?

```sql
SELECT * FROM participants WHERE inn = '986932945';
```

- **«Ko‘rak Kimyo» MChJ**
- Region: Toshkent viloyati; activity: Производитель; role: Продавец; VAT payer: Да
- Expected: name, region, role/activity.

### B3. Products of a company

- RU: Какие товары продаёт компания «Mo‘jotat Klaster» MChJ?
- UZ: «Mo‘jotat Klaster» MChJ qanday tovarlar sotadi?

```sql
WITH top AS (SELECT seller_inn FROM deals_enriched
             WHERE deal_date >= DATE '2025-01-01' AND deal_date < DATE '2026-01-01'
             GROUP BY 1 ORDER BY SUM(sum_uzs) DESC LIMIT 1)
SELECT d.product_name, COUNT(*) AS deals, SUM(d.volume) AS volume, MIN(d.unit) AS unit
FROM deals_enriched d JOIN top ON d.seller_inn = top.seller_inn
GROUP BY 1 ORDER BY deals DESC;
```

- **Пшеница продовольственная Класс 3 класс** — 3 532 deals, 965 812 t
- **Пшеница продовольственная Класс 4 класс** — 3 451 deals, 930 845 t
- Expected: the two product names and deal counts. For a different company, use its INN from
  `search_company` and filter `seller_inn`.

---

## C. Price / volume analytics

### C1. Average caustic soda price in 2023

- RU: Средняя цена за тонну каустической соды в 2023?
- UZ: 2023-yilda kaustik soda tonnasi o‘rtacha narxi?

```sql
SELECT SUM(sum_uzs) / NULLIF(SUM(volume), 0) AS weighted_uzs_per_tonne,
       AVG(sum_uzs / NULLIF(volume, 0)) AS avg_deal_price
FROM deals_enriched
WHERE deal_date >= DATE '2023-01-01' AND deal_date < DATE '2024-01-01'
  AND lower(product_name) LIKE '%сода каустическая%'
  AND unit = 'тонна'
  AND deal_state <> 'Аннулирован(Не оплачен)';
```

- Weighted average: **7 555 568.16 UZS/t** (415 deals, 5 233 t)
- Simple average of deal prices: 7 586 673.94 UZS/t
- Expected: the weighted average, with the definition stated. All these contracts are UZS.

### C2. Most expensive deal of 2026

- RU: Самая дорогая сделка 2026 года в пересчёте на сумы?
- UZ: 2026-yil eng qimmat bitim so‘mda qancha?

```sql
SELECT deal_no, deal_date, product_name, seller_name, buyer_name,
       deal_sum, currency, sum_uzs, deal_state
FROM deals_enriched
WHERE deal_date >= DATE '2026-01-01' AND deal_date < DATE '2027-01-01'
  AND deal_state <> 'Аннулирован(Не оплачен)'
ORDER BY sum_uzs DESC LIMIT 1;
```

- Deal **№547500**, 24.06.2026, Катод медный М00к
- Seller: TIZAHI METALL MCHJ; buyer: «Bejul Savdo» OK
- **1 683 554.25 USD = 22 244 196 225.72 UZS**; state: Исполнен
- Second: №559084, 20 379 160 080.00 UZS (UZS contract)
- Expected: deal number and both the USD amount and the UZS equivalent.

### C3. Cotton sold in Tashkent region

- RU: Сколько тонн хлопка продано в Ташкентской области?
- UZ: Toshkent viloyatida necha tonna paxta sotilgan?

```sql
SELECT COUNT(*) AS deals, SUM(volume) / 1000.0 AS tonnes
FROM deals_enriched
WHERE (lower(product_name) LIKE '%хлопок-сырец%' OR lower(product_name) LIKE '%хлопок сырец%')
  AND unit = 'килограмм'
  AND region = 'Toshkent viloyati'
  AND deal_state <> 'Аннулирован(Не оплачен)';
```

- Excluding cancelled: **528 133.894 tonnes** (8 865 deals)
- All states: 560 559.568 tonnes (9 420 deals)
- Expected: the tonnage, with the note that the source unit is kilograms and the
  conversion `/1000` was applied. `Toshkent viloyati` is the region, not `Toshkent shahri`.

---

## D. States and terms

### D1. Cancelled deals in 2025

- RU: Сколько сделок аннулировано из-за неоплаты в 2025?
- UZ: 2025-yilda to‘lanmaganligi uchun nechta bitim bekor qilingan?

```sql
SELECT COUNT(*) FROM deals
WHERE deal_date >= DATE '2025-01-01' AND deal_date < DATE '2026-01-01'
  AND deal_state = 'Аннулирован(Не оплачен)';
```

- **8 085 deals**

### D2. Executed share of futures

- RU: Доля исполненных сделок по фьючерсам?
- UZ: Fyuchers bitimlarining bajarilgan ulushi?

```sql
SELECT COUNT(*) AS total,
       COUNT(*) FILTER (WHERE deal_state IN ('Исполнен', 'Исполнен(Частично)')) AS completed,
       100.0 * COUNT(*) FILTER (WHERE deal_state IN ('Исполнен', 'Исполнен(Частично)')) / COUNT(*) AS share_all
FROM deals WHERE contract_form = 'Фьючерс';
```

- **80.13%** (5 485 of 6 845) if the denominator is all futures.
- 83.49% if cancelled deals are excluded from the denominator.
- Expected: state the denominator. "Исполнен" includes "Исполнен(Частично)".

---

## E. Export / currency

### E1. Export deals in USD, 2024

- RU: Сумма экспортных сделок в долларах в 2024?
- UZ: 2024-yilda eksport bitimlari dollarda qancha?

```sql
SELECT SUM(deal_sum) AS usd, COUNT(*) AS deals
FROM deals_enriched
WHERE contract_type = 'Экспортный' AND currency = 'USD'
  AND deal_date >= DATE '2024-01-01' AND deal_date < DATE '2025-01-01'
  AND deal_state <> 'Аннулирован(Не оплачен)';
```

- **202 495 621.00 USD** (1 229 deals)

### E2. Same amount in UZS

- RU: Та же сумма в сумах?
- UZ: Xuddi shu summa so‘mda?

```sql
SELECT SUM(sum_uzs) AS uzs FROM deals_enriched
WHERE contract_type = 'Экспортный' AND currency = 'USD'
  AND deal_date >= DATE '2024-01-01' AND deal_date < DATE '2025-01-01'
  AND deal_state <> 'Аннулирован(Не оплачен)';
```

- **2 420 672 267 384.07 UZS**
- Expected: same filter as E1; use the deal-date rate via `sum_uzs`.

---

## F. Brokers

### F1. Broker with the most deals

- RU: Через какого брокера прошло больше всего сделок?
- UZ: Eng ko‘p bitim qaysi broker orqali o‘tgan?

```sql
WITH pairs AS (
  SELECT deal_no, seller_broker AS code FROM deals
  UNION
  SELECT deal_no, buyer_broker AS code FROM deals
)
SELECT b.code, b.name, COUNT(*) AS deals
FROM pairs p JOIN brokers b ON b.code = p.code
GROUP BY 1, 2 ORDER BY deals DESC LIMIT 1;
```

- **BK111 «Gucham Broker» MChJ — 32 422 distinct deals** (either side, no double counting)
- Seller side only: BK111, 21 471 deals.
- Buyer side only: BK017 FIPI BROKER MCHJ, 13 447 deals.
- Expected: BK111 and the counting method. If the bot counts `UNION ALL` it gets 32 983;
  state whether a deal is counted once or twice.

---

## G. Trick questions — must refuse

| # | Question | Why no answer | Expected |
|---|---|---|---|
| G1 | Сколько сделок заключил «Узавтосаноат»? | no such participant (0 matches) | no-answer sentence |
| G2 | Какой курс доллара был 15.06.2030? | rates end 31.10.2026 | no-answer sentence |
| G3 | Savdo bitimlari 2021-yilda qanday bo‘lgan? | deals start 03.01.2022 | no-answer sentence |
| G4 | Кто выиграл последние торги по нефти? | no crude oil; only bitumen products exist | no-answer sentence, or clarify that only bitumen is present |
| G5 | Какая погода была в день сделки №1? | not in the registry | no-answer sentence |

G4 is the only ambiguous one: a `LIKE '%нефть%'` search returns bitumen grades
(`Битум нефтяной …`). If the user means crude oil, there is no answer. The bot should
say the registry has no crude-oil trading data rather than inventing a winner.

---

## Quick data facts

| Fact | Value |
|---|---|
| Deals | 500 000 |
| Contracts | 6 616 |
| Participants | 14 392 |
| Brokers | 120 |
| USD rates | 1 765 |
| Deal dates | 03.01.2022 – 30.10.2026 |
| Rate dates | 01.01.2022 – 31.10.2026 |
| Contract types | Внутренний 493 410; Экспортный 6 590 |
| Contract forms | Спот 456 724; Форвард 36 431; Фьючерс 6 845 |
| States | Исполнен 431 061; Аннулирован 33 719; Исполнен(Частично) 22 648; Оплачен 5 854; Заключен 3 954; Ждёт оплату 1 714; Новый 964; Не подписан 86 |
