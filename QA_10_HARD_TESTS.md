# QA test pack — 10 hard cases for the UZEX spot-registry agent

**Purpose.** These ten cases test whether an AI agent that answers from `deals_2022…2026.csv`,
`contracts.csv`, `participants.csv`, `brokers.csv` and `usd_rates.csv` produces **one correct,
reproducible answer** — and refuses or qualifies when the data cannot support an answer.

**Snapshot.** Deals run 03.01.2022 → 30.10.2026 and every deal state is frozen at the end of
30.10.2026. The FX table runs 01.01.2022 → 31.10.2026. All data is synthetic.

**Verification.** Every number in this document is recomputed from the CSVs by
[`qa/qa_recompute.py`](qa/qa_recompute.py); the 151 anchors in the file all pass. Run it after any
change to the data or to the agent's SQL layer:

```bash
python qa/qa_recompute.py                  # prints every anchor as PASS / FAIL
python qa/qa_recompute.py --xlsx out.xlsx  # also writes the machine-readable answer key
```

A pre-built answer key is at [`qa/answer_key.xlsx`](qa/answer_key.xlsx).

> **What the key is, and is not.** Every number here was computed from the CSVs by
> `qa/qa_recompute.py` — no language model was queried to produce it. The `check` column in the
> workbook says `MATCH` when the value recomputed from the CSVs equals the value frozen in the key
> inside its tolerance; it is a data-consistency check of the answer key, **not** a score of any
> model. Grading an agent means comparing *its* answer against these anchors (§5).

---

## 1. Dataset map and the only correct calculation rules

### 1.1 Files, keys, cardinality

| File | Rows | Grain / key | Joins to |
|---|---:|---|---|
| `deals_2022.csv … deals_2026.csv` | 500,000 total | one row = one deal; `Номер сделки` unique | `Номер контракта` → contracts; `ИНН продавца` / `ИНН покупателя` → participants; `Брокер продавца` / `Брокер покупателя` → brokers; `Дата сделки` → usd_rates |
| `contracts.csv` | 6,616 | one row = one contract card; `Номер контракта` unique | `ИНН продавца` → participants |
| `participants.csv` | 14,392 | one row = one company; `ИНН` unique (9 digits) | — |
| `brokers.csv` | 120 | one row = one brokerage; `Код брокера` unique (`BK001`…`BK120`) | — |
| `usd_rates.csv` | 1,765 | one row per calendar day; `Дата` unique | — |

Per-year deal counts: 2022 = 84,299 · 2023 = 93,985 · 2024 = 106,647 · 2025 = 115,763 · 2026 = 99,306.

### 1.2 Canonical formulas (use these, nothing else)

```text
volume (units)        = Количество × Лот
unit price            = Сумма сделки ÷ (Количество × Лот)          # in the contract currency
UZS amount            = Сумма сделки                              # if contracts.Валюта = "Узбекский сум"
                      = Сумма сделки × usd_rates[Дата сделки]     # if contracts.Валюта = "Доллар США"
delivered volume      = Поставлено × Лот                           # Поставлено counts LOTS
deposit amount        = Сумма сделки × (Сумма залога ÷ 100)        # Сумма залога is "10 %", "15 %", "20 %"
```

**The single most dangerous mistake in this dataset:** the FX rate must be applied **only** to the
148 USD contracts. Multiplying the 493,410 UZS deals by ~12,400 inflates total turnover from
≈220.5 trln UZS to ≈2,515 trln UZS — a 11.4× error that still *looks* like a plausible number.

### 1.3 Field semantics that are easy to get wrong

| # | Field | What it really is | Evidence |
|---|---|---|---|
| 1 | `deals.Регион` | the **seller company's** region from `participants.csv`, not the warehouse region | matches `participants.Регион` of the seller in **100.0000 %** of deals; matches `contracts.Регион` in **0 %** |
| 2 | `contracts.Регион` | warehouse region, written in **Russian** (`г. Ташкент`, `Наманганская область`) while `participants.Регион` is Latin (`Toshkent shahri`) | the two vocabularies never intersect → every join between them returns 0 rows |
| 3 | `participants.Роль` | 392 rows are `Продавец`, 14,000 are `Покупатель` | the 392 sellers own all 6,616 contracts (avg 16.9, max 60) |
| 4 | `Количество` | **lots**, not units | `Лот` ranges 1…1000 |
| 5 | `Поставлено` | delivered **lots** (empty = nothing delivered yet) | empty in exactly 46,291 deals = the sum of the six non-delivered states |
| 6 | `Сумма сделки` | in the **contract** currency; USD for the 148 export contracts | `Тип контракта = Экспортный` ⇔ `Валюта = Доллар США`, 6,590 deals both ways |
| 7 | `Единица измерения` | 7 distinct units; physical totals across units are meaningless | tonnes 23.98 m, kg 9,803.9 m, litres 475.2 m, pieces 131.5 m, metres 3.95 m, m² 1.60 m, m³ 0.35 m |
| 8 | `Наименование товара` | seller free text; 697 spellings, and 66 different spellings of cotton alone (TN VED 520100) | group by `Код ТН ВЭД`, not by the name string |
| 9 | `Номер сделки` | 100,001…604,956 with **4,956 gaps** | max ≠ row count |
| 10 | `usd_rates` | daily, non-monotonic; 822 days closed lower than the previous day | 10,829.10 → 13,500.03, min on 01.01.2022, max on 22.09.2026 |
| 11 | `Состояние сделки` | 8 states; `Аннулирован(Не оплачен)` is *not* turnover | 33,719 deals / 14.738 trln UZS |
| 12 | `contracts.Действует до` | no deal violates its contract window | 0 deals before registration, 0 after expiry |

### 1.4 Scoring model

Each case has an **anchor checklist** (numbers with an absolute tolerance). Score a run as:

| Verdict | Rule |
|---|---|
| **PASS** | every critical anchor inside tolerance **and** no fatal error from §1.5 |
| **PARTIAL** | ≥ 80 % of anchors inside tolerance, no fatal error |
| **FAIL** | any fatal error, or < 80 % of anchors, or a number invented with no basis in the files |

Answers must state the unit of every figure (UZS / USD / tonnes / lots / deals) and, where a
definition was needed, state the definition it used. An answer that is numerically right but
silently mixes currencies or units is a FAIL.

### 1.5 The 12 fatal errors

| # | Fatal error | Typical symptom |
|---|---|---|
| F1 | multiplying UZS deal sums by the FX rate | total turnover ≈ 2,515 trln instead of 220.477 trln |
| F2 | treating export deal sums as if they were already UZS | export segment ≈ $1.14 bn reported as "1.14 trln UZS" |
| F3 | summing `Количество` without `× Лот` | volumes 1,000× too small |
| F4 | treating `Поставлено` as units | partial-delivery backlog 1,000× too small |
| F5 | ranking products by raw volume across different units | cotton "1.33 billion" beats wheat "2.33 million" |
| F6 | joining `contracts.Регион` to `participants.Регион` | zero rows, or a silent fallback to the wrong region |
| F7 | using 604,956 (max deal number) as the deal count | count 21 % too high |
| F8 | claiming "all deals were executed" | ignores 33,719 annulled + 22,648 partially delivered |
| F9 | including annulled deals in turnover without saying so | +6.68 % on every value figure |
| F10 | converting all export deals at one rate (year-end or average) | 2025 export off by +27.39 bn UZS (+1.00 %) |
| F11 | comparing 2026 YTD with full-year 2025 | "2026 is down 14 %" instead of "+10.6 % on the same window" |
| F12 | inventing profit, margin, VAT amounts, costs or forecasts | the files contain no such fields |

---

## 2. The ten cases

---

### CASE 01 — Export segment 2025: per-deal FX conversion

**Files:** all five deal files + contracts + usd_rates. **Difficulty:** hard. **Skills:** currency
semantics, per-row FX join, share-of-total, error quantification.

**Question (EN).**
> For 2025, size the export segment of the exchange. How many export deals were there, what was
> their total contract value in USD, what is that worth in UZS, what share of 2025 turnover does it
> represent, and what effective UZS/USD rate does the segment imply? Then show what happens if
> someone converts the whole segment at the 31.12.2025 rate of 12,552.58 — how large is that error
> in UZS and in percent?

**Вопрос (RU).**
> Оцените экспортный сегмент биржи за 2025 год: сколько экспортных сделок, какова их сумма в
> долларах, сколько это в сумах, какую долю оборота 2025 года это составляет и какой эффективный
> курс сум/доллар из этого следует? Затем покажите, что получится, если пересчитать весь сегмент
> по курсу 12 552,58 на 31.12.2025 — какова ошибка в сумах и в процентах?

**Savol (UZ).**
> 2025-yil eksport segmentini baholang: nechta eksport bitimi, dollarda umumiy summa, so‘mda qancha,
> 2025-yil aylanmasining qancha foizi va qanday samarali so‘m/dollar kursi kelib chiqadi? So‘ngra
> butun segmentni 31.12.2025 dagi 12 552,58 kurs bo‘yicha hisoblasangiz — xato so‘mda va foizda qancha?

**Reference answer.**

An export deal is a deal whose contract carries `Валюта = Доллар США` (equivalently
`Тип контракта = Экспортный`; the two classifications agree on all 500,000 rows: 6,590 export
deals, 148 export contracts, 142 of them actually traded).

For 2025:

| Metric | Value |
|---|---:|
| Export deals | **1,367** |
| Total contract value | **$220,524,617.85** |
| Value in UZS at each deal's own date rate | **2,740,766,106,533.96 UZS** (≈ 2.7408 trln) |
| 2025 turnover, all deals | 55.977 trln UZS (115,763 deals) |
| Export share of 2025 value | **4.8963 %** |
| Export share of 2025 deal count | **1.1809 %** |
| Effective rate (UZS ÷ USD, value-weighted) | **12,428.3907** |
| Average export deal | $161,320 (vs $38,906 for an average 2025 deal overall) |

The export segment is 1.18 % of deals but 4.90 % of value: an export deal is ≈ 4.1× larger than an
average deal. For context, the export share of value by year is 8.7419 % (2022), 6.4326 % (2023),
5.7110 % (2024), 4.8963 % (2025), 6.3547 % (2026 YTD).

Conversion at the single 31.12.2025 rate instead of each deal-date rate:

```text
220,524,617.85 × 12,552.58 = 2,768,152,907,531.55 UZS
2,768,152,907,531.55 − 2,740,766,106,533.96 = +27,386,800,997.60 UZS
+27.39 bn UZS  =  +0.9992 %
```

So a single-rate conversion overstates the segment by ≈ 27.4 bn UZS (+1.00 %). The direction is not
accidental: the 2025 rates applied to these deals ranged 12,181.16 (08.09.2025) … 12,666.90
(11.04.2025), and the 31.12.2025 rate of 12,552.58 sits above the deal-weighted average of
12,428.39 — so a year-end rate is systematically above the rates of the earlier months. The same
calculation on the whole period gives 6,590 export deals, $1,137,509,729.39 and 13.642 trln UZS at an
effective rate of 11,992.81.

**Anchor checklist.**

| Anchor | Expected | Tol |
|---|---:|---:|
| Q1_2025_export_n | 1,367 deals | 0 |
| Q1_2025_export_usd | 220,524,617.85 USD | 100 |
| Q1_2025_export_uzs | 2,740,766,106,533.96 UZS | 50 m |
| Q1_eff_rate | 12,428.3907 | 0.5 |
| Q1_share_value_pct | 4.8963 % | 0.02 |
| Q1_share_count_pct | 1.1809 % | 0.01 |
| Q1_at_ye_rate | 2,768,152,907,531.55 UZS | 50 m |
| Q1_error_vs_ye | +27,386,800,997.60 UZS | 5 m |
| Q1_error_pct | +0.9992 % | 0.01 |

**Rubric.** PASS requires: (a) export identified via the contract currency, (b) per-deal-date rate
used for the primary figure, (c) the 31.12.2025 comparison computed and labelled as an error, (d)
the sign of the error (overstatement) stated. Reporting the segment as "2,740,766,106,533.96 USD"
or "2.74 trln USD" is a FAIL (unit confusion).

**Fatal errors:** F2, F10.

**Follow-up probes.** What is the effective rate for the whole 2022–2026 period (11,992.81)? Which
single month of 2025 had the highest export value? If you had to state one number for "2025 export
turnover in USD", would you use 220.5 m or 2,740.8 trln, and why?

---

### CASE 02 — Price formation by auction type in 2024

**Files:** `deals_2024.csv` + `contracts.csv` + `usd_rates.csv`. **Difficulty:** hard.
**Skills:** unit-price derivation, lot handling, weighted vs unweighted statistics, sign semantics.

**Question (EN).**
> For 2024 only, compare the three trading mechanisms. For each (`Английский аукцион`,
> `Двусторонний аукцион`, `Обратный аукцион`) give the deal count, the mean and median percentage
> deviation of the realised unit price from the start price, the observed range, how many deals
> closed exactly at the start price, and the aggregate premium or discount in UZS. Then state the
> net effect of the auction mechanism on 2024 turnover.

**Вопрос (RU).**
> Только за 2024 год сравните три механизма торгов. По каждому (`Английский аукцион`,
> `Двусторонний аукцион`, `Обратный аукцион`) дайте число сделок, среднее и медианное отклонение
> фактической цены за единицу от стартовой в процентах, наблюдавшийся диапазон, сколько сделок
> закрылось ровно по стартовой цене и совокупную премию или дисконт в сумах. Затем назовите чистый
> эффект механизма торгов на оборот 2024 года.

**Savol (UZ).**
> Faqat 2024-yil uchun uchta savdo mexanizmini taqqoslang. Har biri bo‘yicha (`Английский аукцион`,
> `Двусторонний аукцион`, `Обратный аукцион`) bitimlar soni, birlik narxining boshlang‘ich narxdan
> o‘rtacha va mediana chetlanishi (foizda), kuzatilgan diapazon, boshlang‘ich narxda yopilgan
> bitimlar soni va so‘mda umumiy premiya yoki diskontni bering. So‘ngra savdo mexanizmining 2024-yil
> aylanmasiga sof ta’sirini ayting.

**Reference answer.**

Unit price must be derived, never read: `unit price = Сумма сделки ÷ (Количество × Лот)`. Deviation
is `unit price ÷ Стартовая цена − 1`. 2024 contains 106,647 deals worth 45.901 trln UZS.

| Mechanism | Deals | Share of deals | Mean dev. | Median dev. | Range | At exact start | Aggregate effect |
|---|---:|---:|---:|---:|---:|---:|---:|
| Английский аукцион (ascending) | 55,076 | 51.64 % | **+3.2430 %** | +1.3038 % | 0 … +40.0006 % | **19,398** (35.22 %) | **+665.0 bn UZS** |
| Двусторонний аукцион (two-sided) | 49,004 | 45.95 % | **−1.5020 %** | −1.5032 % | −3.0578 % … 0 | **1** | **−372.4 bn UZS** |
| Обратный аукцион (descending) | 2,567 | 2.41 % | **−5.7439 %** | −4.1195 % | −35.0001 % … −0.0046 % | **0** | **−20.4 bn UZS** |

Net effect: `+665.0 − 372.4 − 20.4 = +272.2 bn UZS`, i.e. **+0.5926 % of the 45.901 trln UZS 2024
turnover**.

Reading of the mechanism:
* Ascending auctions never clear below the start price (the largest negative deviation is a rounding
  artefact below 0.05 UZS of deal sum), rise up to the +40 % ceiling and are the only mechanism that
  produces a premium: 35.2 % of them close at the start price, the rest bid up.
* Two-sided auctions clear between −3.06 % and the start price; every one of them is at or below
  the start price, and exactly one closes at it.
* Descending auctions clear strictly below the start price, with the deepest cut at −35.00 %, and
  none closes at the start price.
* Because 51.6 % of deals are ascending and their premium is not offset by the two discounting
  mechanisms, the auction design adds ≈ 0.59 % to total value — small in percentage terms but
  272 bn UZS in absolute terms.

Note on the "at exact start" count: measured as `|Сумма сделки − Количество × Лот × Стартовая цена|
< 1 UZS`, which is the precision of the stored sum (one decimal). Exact product equality yields
18,684 ascending + 1 two-sided = 18,685; the 1-soum tolerance adds 714 ascending deals whose stored
sum is rounded below the product. Both figures are defensible; the answer must state which one it
used.

**Anchor checklist.**

| Anchor | Expected | Tol |
|---|---:|---:|
| Q2_eng_n | 55,076 | 0 |
| Q2_eng_avg | +3.2430 % | 0.005 |
| Q2_eng_med | +1.3038 % | 0.005 |
| Q2_eng_max | +40.0006 % | 0.005 |
| Q2_eng_at_start | 19,398 | 0 |
| Q2_eng_prem_bn | +665.0 bn UZS | 2 |
| Q2_dbl_n | 49,004 | 0 |
| Q2_dbl_avg | −1.5020 % | 0.005 |
| Q2_dbl_at_start | 1 | 0 |
| Q2_rev_at_start | 0 deals | 0 |
| Q2_dbl_prem_bn | −372.4 bn UZS | 2 |
| Q2_rev_n | 2,567 | 0 |
| Q2_rev_avg | −5.7439 % | 0.005 |
| Q2_rev_min | −35.0001 % | 0.005 |
| Q2_rev_prem_bn | −20.4 bn UZS | 2 |
| Q2_net_prem_bn | +272.2 bn UZS | 2 |
| Q2_net_pct | +0.5926 % | 0.01 |

**Rubric.** PASS requires the unit price to be **derived** (a run that averages `Сумма сделки`
instead of the unit price cannot produce +3.24 %), the three signs to be correct, and the net effect
to be stated both in UZS and as a percentage of 2024 turnover.

**Fatal errors:** F3 (ignoring `Лот`), plus any claim that ascending auctions clear below the start
price or that two-sided auctions clear above it.

**Follow-up probes.** If you weight the deviation by deal value instead of by deal, the ascending
premium becomes +3.4717 % — why is the value-weighted number higher? (Answer: bigger deals bid
further above the start.) Which mechanism dominates a *commodity* such as wheat or cement?

---

### CASE 03 — Deal states: what actually happened, and what the deposit exposure is

**Files:** all deal files + contracts. **Difficulty:** hard. **Skills:** state semantics, value vs
count weighting, derived exposure, snapshot reasoning.

**Question (EN).**
> Give the full distribution of the eight deal states by count, share of deals, value in UZS and
> share of value. How much turnover never materialised, and how much of that is covered by the
> contractual deposit? Which states can only exist because the snapshot is 30.10.2026, and what
> does that imply for year-over-year comparisons?

**Вопрос (RU).**
> Дайте полное распределение восьми состояний сделок: количество, доля сделок, стоимость в сумах и
> доля стоимости. Какая часть оборота не состоялась и какая её часть покрыта договорным залогом?
> Какие состояния могут существовать только потому, что выгрузка сделана 30.10.2026, и что это
> значит для сравнений год к году?

**Reference answer.**

Total: 500,000 deals, 220.477 trln UZS.

| State | Deals | % of deals | Value, trln UZS | % of value |
|---|---:|---:|---:|---:|
| Исполнен (paid and fully delivered) | 431,061 | 86.2122 % | 188.316 | 85.4130 % |
| Аннулирован(Не оплачен) (cancelled, unpaid) | **33,719** | **6.7438 %** | **14.738** | **6.6848 %** |
| Исполнен(Частично) (partially delivered) | 22,648 | 4.5296 % | 9.705 | 4.4017 % |
| Оплачен (paid, not shipped) | 5,854 | 1.1708 % | 3.328 | 1.5095 % |
| Заключен (forward/futures signed) | 3,954 | 0.7908 % | 2.809 | 1.2739 % |
| Ждёт оплату (spot signed, awaiting payment) | 1,714 | 0.3428 % | 0.943 | 0.4278 % |
| Новый (booked on 30.10.2026) | 964 | 0.1928 % | 0.598 | 0.2713 % |
| Не подписан (unsigned) | 86 | 0.0172 % | 0.040 | 0.0180 % |

Turnover that never materialised: **33,719 deals / 14.738 trln UZS = 6.6848 % of gross value**
(6.7438 % of deals). Excluding it, "valid" turnover is 205.739 trln UZS.

Deposit: `Сумма залога` is 10 % (456,724 deals), 15 % (36,431) or 20 % (6,845). Total deposit
implied by all deals is **23.545 trln UZS**, of which **1.538 trln (6.5326 %)** sits on deals that
were annulled. So the deposit covers only about a tenth of the annulled value (1.538 / 14.738 =
10.4 %) — the guarantee fund is far from covering non-payment risk. (The data does not say that
deposits were forfeited; it only supports the deposit amount.)

Snapshot logic: the five non-terminal states — `Новый` (964), `Не подписан` (86), `Ждёт оплату`
(1,714), `Заключен` (3,954), `Оплачен` (5,854) — occur **only in 2026**, because a 2022–2025 deal
cannot still be pending on 30.10.2026. That also means 2026 is an unbalanced year: 12,572 of its
99,306 deals (12.66 %) are still open, so year-over-year value comparisons must either fix the
window (see CASE 10) or normalise by state.

**Anchor checklist.**

| Anchor | Expected | Tol |
|---|---:|---:|
| Q3_done_n / pct_n / tln / pct_v | 431,061 / 86.2122 % / 188.316 / 85.4130 % | 0 / 0.01 / 0.02 / 0.02 |
| Q3_ann_n / pct_n / tln / pct_v | 33,719 / 6.7438 % / 14.738 / 6.6848 % | 0 / 0.01 / 0.02 / 0.02 |
| Q3_part_n / tln | 22,648 / 9.705 | 0 / 0.02 |
| Q3_paid_n / signed_n / wait_n / new_n / unsigned_n | 5,854 / 3,954 / 1,714 / 964 / 86 | 0 |
| Q3_deposit_all_tln | 23.545 trln UZS | 0.02 |
| Q3_deposit_ann_tln | 1.538 trln UZS | 0.01 |
| Q3_deposit_ann_share | 6.5326 % | 0.02 |

**Rubric.** PASS requires all eight states (no collapsing into "executed / not executed"), the
difference between share-of-count and share-of-value (86.21 % vs 85.41 %), and the "open states only
in 2026" observation.

**Fatal errors:** F8, F9, F12 (claiming deposits were forfeited).

**Follow-up probes.** What is the annulled share by year (by value 6.58 % / 6.63 % / 6.92 % / 7.00 % /
6.24 %; by count 6.80 % / 6.72 % / 6.87 % / 6.98 % / 6.31 % for 2022→2026)? Which single state has
the largest *absolute* gap between count share and value share, and why?

---

### CASE 04 — Partial delivery: the real backlog

**Files:** all deal files + contracts + usd_rates. **Difficulty:** hard. **Skills:** lots vs units,
`Поставлено`, unit-price valuation, category aggregation.

**Question (EN).**
> `Исполнен(Частично)` means the buyer paid and only part of the goods was delivered. Quantify that
> backlog: how many deals, how many lots and how many physical units were never delivered, what is
> that worth in UZS at the deal unit price, what is the aggregate fill rate, which product category
> carries most of the exposure, and what is the single largest shortfall?

**Вопрос (RU).**
> `Исполнен(Частично)` означает, что покупатель оплатил, а товар поставлен лишь частично.
> Оцените этот «хвост»: сколько сделок, сколько лотов и сколько физических единиц не поставлено,
> сколько это стоит в сумах по цене сделки за единицу, каков совокупный коэффициент поставки, на
> какую категорию товара приходится основная часть и какая отдельная сделка даёт наибольший
> недопоставленный объём?

**Reference answer.**

| Metric | Value |
|---|---:|
| Deals in `Исполнен(Частично)` | **22,648** (4.53 % of all deals) |
| Contracted volume in those deals | 452,682,034 units* |
| Delivered | 280,242,373 units |
| **Never delivered** | **151,667,030 lots → 172,439,661 units** |
| Value of the shortfall at deal unit price | **3.777 trln UZS = 38.92 % of the 9.705 trln UZS contracted value of these deals** |
| Aggregate fill rate (delivered volume ÷ contracted volume) | **62.1046 %** |
| Average per-deal fill rate | 60.8668 % |
| Largest single shortfall | **302,376 lots** — deal 373,855 (20.11.2024): 442,215 lots bought, 139,839 delivered |

\* contracted = `Количество × Лот`, delivered = `Поставлено × Лот`; both are sums over a mixed set of
units, so the *unit* figures are only meaningful inside a single unit of measure — the UZS figures
are the portable ones.

Exposure by product category (value of undelivered goods, trln UZS):

| Category | trln UZS | Share |
|---|---:|---:|
| Сельскохозяйственная продукция | **1.938** | 51.3 % |
| Продовольственные товары | 0.505 | 13.4 % |
| Нефтепродукты | 0.446 | 11.8 % |
| Металлопродукция | 0.370 | 9.8 % |
| Полимерная продукция | 0.270 | 7.1 % |
| Химическая продукция | 0.132 | 3.5 % |
| Строительные материалы | 0.114 | 3.0 % |
| Промышленные товары | 0.002 | 0.1 % |

By product group: high-liquidity goods 3.427 trln (90.7 %), other goods 0.350 trln (9.3 %).

Interpretation: 4.5 % of deals are stuck at ~62 % delivery, which is 3.78 trln UZS of paid-for goods
not shipped. Agriculture alone accounts for half of it, consistent with cotton being the dominant
kg-denominated product.

**Anchor checklist.**

| Anchor | Expected | Tol |
|---|---:|---:|
| Q4_deals | 22,648 | 0 |
| Q4_und_lots | 151,667,030 lots | 0 |
| Q4_und_vol | 172,439,661 units | 0 |
| Q4_tln | 3.777 trln UZS | 0.01 |
| Q4_fill_pct | 62.1046 % | 0.02 |
| Q4_avg_fill_pct | 60.8668 % | 0.02 |
| Q4_agri_tln | 1.938 trln UZS | 0.01 |
| Q4_max_und_lots | 302,376 lots | 0 |

**Rubric.** PASS requires `Поставлено × Лот` (not `Поставлено` alone), valuation at the deal's own
unit price in its own currency with FX conversion for USD contracts, and the aggregate-vs-average
fill-rate distinction.

**Fatal errors:** F4, F3, F9.

**Follow-up probes.** How much of the 3.777 trln backlog is in USD contracts? Which TN VED code has
the largest undelivered tonnage (520100)? If all partial deals completed tomorrow, by how much would
delivered volume rise in percentage terms?

---

### CASE 05 — "Which product moved the most in 2026?" — the unit trap

**Files:** `deals_2026.csv` + contracts. **Difficulty:** hard. **Skills:** unit awareness, refusing
an ill-posed comparison, normalising kg → t, name-variant handling.

**Question (EN).**
> Which product had the largest physical volume in 2026? Give the top three with numbers, explain
> exactly how you made them comparable, and say whether a single "total physical volume for 2026"
> figure can be quoted at all.

**Вопрос (RU).**
> Какой товар в 2026 году имел наибольший физический объём? Назовите тройку лидеров с цифрами,
> объясните, как именно вы привели их к сопоставимому виду, и скажите, можно ли вообще назвать
> единую цифру «общий физический объём за 2026 год».

**Savol (UZ).**
> 2026-yilda qaysi tovar eng katta jismoniy hajmga ega bo‘ldi? Uchlikni raqamlar bilan ayting,
> ularni qanday taqqoslanadigan holatga keltirganingizni tushuntiring va umuman «2026-yil uchun
> umumiy jismoniy hajm» degan yagona raqamni aytish mumkinmi?

**Reference answer.**

A single total cannot be quoted. 2026 deals are recorded in **7 different units of measure** and the
`Количество × Лот` figures are not additive across them:

| Unit | Deals 2026 | Raw "volume" |
|---|---:|---:|
| тонна | 57,256 | 5,217,442 |
| килограмм | 34,134 | 1,602,333,228 |
| литр | 3,276 | 126,479,000 |
| штука | 1,860 | 27,299,050 |
| куб.метр | 1,189 | 79,467 |
| кв.метр | 808 | 328,285 |
| метр | 783 | 776,957 |

Summing the column gives 1,762,513,429 "units" — a number with no meaning, because 1 kg and 1 tonne
are counted as equal. Only tonne and kilogram are convertible; litres, pieces, metres and m²/m³ are
not convertible to mass without density/weight assumptions that the files do not provide.

Converting kg → t where possible, 2026 ranking by mass:

| Rank | Product (TN VED) | Tonnes | Deals |
|---|---|---:|---:|
| **1** | **Пшеница продовольственная (100199)** | **2,330,761** | 8,351 |
| **2** | **Портландцемент (252329)** | **1,367,297** | 8,587 |
| **3** | **Хлопок-сырец (520100)** | **1,331,974.8** | 22,384 |
| 4 | Дизельное топливо / мазут (271019) | 229,852.7 | 7,057 |
| 5 | Аммиачная селитра (310230) | 171,354 | 2,042 |
| 6 | Карбамид (310210) | 163,097 | 2,368 |
| 7 | Масло хлопковое (151229) | 122,591 | 2,444 |
| 8 | Шрот хлопковых семян (230610) | 117,400.5 | 1,526 |

**The trap.** Cotton is recorded in **kilograms** (1,331,974,809 kg) while wheat and cement are in
tonnes. A naive `SUM(Количество × Лот) GROUP BY product` puts cotton first with 1,331,974,809 —
about 1,000× its true mass — and leaves wheat (2,330,761) far outside the top five, behind
kg-denominated cottonseed meal (117,400,465), flour (112,123,900) and light diesel (126,536,235).
Correctly normalised, cotton is **third**, and even cement barely beats it (1,367,297 t vs
1,331,974.8 t, a 2.6 % margin). So the correct answer to "largest physical volume in 2026" is
**wheat, 2.33 m t**, *conditional on* converting kg to t and on excluding non-mass units.

Product identity must be taken from `contracts.Код ТН ВЭД`, not from `Наименование товара`: there
are 66 different spellings of cotton alone (`Хлопок-сырец (спот)`, `Хлопок сырец (спот)`,
`ХЛОПОК-СЫРЕЦ`, `Хлопок-сырец (форвард)`, sorts and classes appended…). Ranking by raw name
fragments the same commodity into dozens of rows.

**Anchor checklist.**

| Anchor | Expected | Tol |
|---|---:|---:|
| Q5_wheat_t | 2,330,761 t | 0 |
| Q5_cement_t | 1,367,297 t | 0 |
| Q5_cotton_t | 1,331,974.8 t | 0.5 |
| Q5_cotton_kg | 1,331,974,809 kg | 0 |
| Q5_naive_cotton | 1,331,974,809 (mixed units) | 0 |
| Q5_units_2026 | 7 | 0 |

**Rubric.** PASS requires the agent to **refuse the cross-unit ranking**, state the 7 units, convert
kg → t, and name wheat as #1 with cotton #3. Answering "cotton, 1.33 billion" is a FAIL even though
the arithmetic on the raw column is "correct".

**Fatal errors:** F5, and any invented density/weight conversion for litres or pieces.

**Follow-up probes.** What happens if you rank by value instead of volume (cotton still #1 by
UZS)? Which product is #1 in tonnes across all five years? How would you answer "total tonnage
2026" honestly (sum only tonnes + kg/1000, and label it "mass-denominated products only")?

---

### CASE 06 — Broker league table 2025, and the difference between counting and valuing

**Files:** deal files + brokers + participants + contracts. **Difficulty:** medium-hard.
**Skills:** two-sided broker roles, code→name join, count vs value ranking, data completeness.

**Question (EN).**
> Build the 2025 seller-side broker league table. Who are the top five by UZS value, with deal counts
> and shares; who are the bottom three; and does the broker that handles the most deals also handle
> the most value? Which brokers never act for a seller at all, and how many of the 120 firms were
> active on the seller side in 2025?

**Вопрос (RU).**
> Постройте рейтинг брокеров со стороны продавца за 2025 год. Кто входит в топ-5 по сумме в сумах
> (с количеством сделок и долями), кто внизу, и совпадает ли лидер по количеству сделок с лидером
> по сумме? Какие брокеры вообще ни разу не выступали за продавца и сколько из 120 контор были
> активны на стороне продавца в 2025 году?

**Reference answer.**

Scope: 2025, 115,763 deals, 55.977 trln UZS, attributed to `Брокер продавца` (a deal is counted
once, on the sell side — never on both sides, or the total doubles).

| Rank | Code | Name | Deals | Value, bn UZS | Share of 2025 |
|---:|---|---|---:|---:|---:|
| 1 | BK111 | "Gucham Broker" MChJ | 4,128 | **3,731.779** | **6.6667 %** |
| 2 | BK106 | PASUR BROKER MCHJ | 3,838 | 3,309.500 | 5.9123 % |
| 3 | BK102 | "Shofin Broker" MChJ | 3,606 | 2,276.498 | 4.0669 % |
| 4 | BK047 | "Somot Broker" MChJ | 3,345 | 2,202.409 | 3.9345 % |
| 5 | BK005 | NAXON BROKER AJ | **4,652** | 1,822.390 | 3.2556 % |

Bottom three: BK031 "Nashuya Broker" MChJ — 8 deals, 0.101 bn; BK051 "Tiren Broker" MChJ — 25 deals,
0.599 bn; BK069 BIXO‘TU BROKER… — 18 deals, 7.295 bn.

Count vs value: **no**. BK005 handles the most deals (4,652, 4.02 % of all 2025 deals) but is only
5th by value (1,822.390 bn, 3.26 %): its average deal is 392 m UZS, while BK111's is 904 m UZS.
Ranking by count alone gives a different top-3 (BK005, BK111, BK106).

Coverage: 113 of the 120 brokers were active on the seller side in 2025 (116 over the whole
2022–2026 period), while all 120 appear as buyer-side brokers. Four firms **never** act for a
seller: **BK004 "КОТОТ БРОКЕР" МЧЖ, BK019 "Kizo‘qen Broker" MChJ, BK104 "Quvo‘ Broker" MChJ,
BK113 "Shumuz Broker" XK**. They are buy-side-only intermediaries — a correct answer must not
describe them as "inactive", because each has buyer-side volume.

**Anchor checklist.**

| Anchor | Expected | Tol |
|---|---:|---:|
| Q6_bk111_n / bn / share | 4,128 / 3,731.779 bn / 6.6667 % | 0 / 0.5 / 0.01 |
| Q6_bk106_n / bn | 3,838 / 3,309.500 bn | 0 / 0.5 |
| Q6_bk102_bn / Q6_bk047_bn | 2,276.498 / 2,202.409 bn | 0.5 |
| Q6_bk005_n / bn | 4,652 / 1,822.390 bn | 0 / 0.5 |
| Q6_bk031_n / bn | 8 / 0.101 bn | 0 / 0.01 |
| Q6_never_seller | 4 brokers | 0 |
| Q6_active_2025 | 113 | 0 |

**Rubric.** PASS requires: seller-side attribution only (no double counting), the four buy-side-only
codes named, and the explicit count-vs-value divergence.

**Fatal errors:** summing both broker columns (turnover doubles to 111.95 trln); calling BK004 et al.
"inactive"; ranking by code string (`BK100` < `BK099` lexicographically).

**Follow-up probes.** What is the Herfindahl-style concentration — top-10 brokers' share of 2025
value? Which broker pair (seller broker + buyer broker) appears most often?

---

### CASE 07 — Registry integrity audit (the "count carefully" case)

**Files:** all files. **Difficulty:** medium-hard. **Skills:** counting, key ranges, referential
integrity, distinguishing "registered" from "traded".

**Question (EN).**
> Audit the registry. State: total deals and the deal-number range with the number of missing
> numbers; how many contracts exist, how many were used, and the currency split of the unused ones;
> how many companies are registered, how many actually trade, and how many are sellers vs buyers; how
> many brokers exist and how many never act for a seller; the FX table's coverage and whether the
> rate is monotonic; whether any deal is an orphan; and the number of distinct trading days.

**Вопрос (RU).**
> Проведите аудит реестра. Укажите: общее число сделок и диапазон номеров с числом пропущенных
> номеров; сколько контрактов заведено, сколько использовано и каково распределение
> неиспользованных по валюте; сколько компаний зарегистрировано, сколько реально торгует и сколько
> из них продавцы и покупатели; сколько брокеров и сколько ни разу не выступали за продавца;
> покрытие таблицы курса и монотонен ли курс; есть ли «осиротевшие» сделки; и число различных
> торговых дней.

**Reference answer.**

| Check | Result |
|---|---|
| Deals | **500,000** rows (2022: 84,299 · 2023: 93,985 · 2024: 106,647 · 2025: 115,763 · 2026: 99,306) |
| Deal numbers | 100,001 … 604,956 → span **504,956**, so **4,956 numbers are missing**, 0 duplicates |
| Contracts | **6,616** total, **6,483** used, **133 unused (2.0103 %)** — 127 UZS + 6 USD |
| Companies | **14,392**: 392 `Продавец` + 14,000 `Покупатель`; **14,389 trade**, **3 never trade** (all three are buyers: 934519810 MAFUZ INVEST, 937876670 "РИЧАМ ҚУРИЛИШ", 975709868 YENEM SERVIS) |
| Seller/buyer reality | deals involve **392 distinct sellers** (every registered seller, avg 16.9 contracts, max 60) and **13,997 distinct buyers**; **no company ever appears on both sides** |
| Brokers | **120**; **4 never act for a seller** (BK004, BK019, BK104, BK113); 116 do |
| FX table | **1,765 rows, 01.01.2022 – 31.10.2026, zero missing calendar days**, 10,829.10 → 13,500.03; **not monotonic** — 822 days closed below the previous day |
| Orphans | **0**: every deal's contract, seller, buyer, both brokers and deal-date rate resolve |
| Trading days | **1,236 distinct dates**, all weekdays (0 Saturday/Sunday), sessions 10:00:00 – 16:59:59 |
| Contract windows | **0** deals before `Дата регистрации`, **0** after `Действует до` |

The 4,956 missing deal numbers matter: `MAX(Номер сделки) − MIN(Номер сделки) + 1 = 504,956`, not
500,000. Any answer that says "deal numbers run to 604,956, so there are 604,956 deals" is wrong by
104,956 (21.0 %).

**Anchor checklist.**

| Anchor | Expected | Tol |
|---|---:|---:|
| G_deals | 500,000 | 0 |
| Q7_span / Q7_gaps / Q7_dup | 504,956 / 4,956 / 0 | 0 |
| G_contracts / G_contracts_used / G_contracts_unused | 6,616 / 6,483 / 133 | 0 |
| Q7_unused_uzs / Q7_unused_usd | 127 / 6 | 0 |
| G_participants / Q7_p_unused | 14,392 / 3 | 0 |
| G_sellers / G_buyers | 392 / 13,997 | 0 |
| G_brokers / Q6_never_seller | 120 / 4 | 0 |
| Q7_rate_days / Q7_rate_missing | 1,765 / 0 | 0 |
| Q7_rate_min / Q7_rate_max | 10,829.10 / 13,500.03 | 0.01 |
| Q7_rate_down_days | 822 | 0 |
| Q7_orphans | 0 | 0 |
| Q7_deal_dates / Q7_weekend | 1,236 / 0 | 0 |

**Rubric.** PASS requires all ten lines. A single wrong count fails the case — this is the case
that catches hallucinated inventory numbers.

**Fatal errors:** F7, plus claiming orphans exist or that the rate is monotonic.

**Follow-up probes.** How many contracts belong to the largest seller (60)? Which month has the fewest
deals (2022-02, 3,979)? Is there any deal dated on a holiday that has no FX rate (no)?

---

### CASE 08 — Payment and delivery discipline

**Files:** all deal files + contracts. **Difficulty:** medium-hard. **Skills:** date arithmetic,
contract-term lookups, separating "late payment" from "late delivery", value weighting.

**Question (EN).**
> Using `Срок оплаты` (days from the deal date) and `Срок поставки` (days from the payment date),
> assess compliance: how many deals have been paid, how many were paid late, what is the maximum
> payment delay allowed and observed; how many have been delivered, how many were delivered late,
> by how many days on average and at worst, what value is affected, and which category is the worst
> offender?

**Вопрос (RU).**
> Используя `Срок оплаты` (дней от даты сделки) и `Срок поставки` (дней от даты оплаты), оцените
> дисциплину: сколько сделок оплачено, сколько оплачено с нарушением срока, каков максимальный
> разрешённый и фактический срок оплаты; сколько поставлено, сколько поставлено с нарушением, на
> сколько дней в среднем и максимум, какая стоимость затронута и какая категория хуже всех?

**Reference answer.**

Payment side: **459,563** deals have `Дата оплаты` (91.9 %). Contract terms run 3…90 days (median 7).
Actual payment lag runs 0…90 days (median 3). **Late payments: 0.** Every payment date is within its
contractual term — 387,941 deals paid early, 71,622 exactly on the term. So "payment discipline" is
perfect in this dataset, and any answer claiming late payments is inventing data.

Delivery side: **453,709** deals have `Дата поставки`. Contract delivery terms run 5…60 days;
actual delivery lag runs 1…75 days.

| Metric | Value |
|---|---:|
| Delivered late (`Дата поставки − Дата оплаты > Срок поставки`) | **17,805 deals = 3.9243 %** |
| Average overrun among late deals | **7.9504 days** |
| Maximum overrun | **15 days** |
| Value affected | **7.705 trln UZS = 3.8910 % of the 198.021 trln UZS shipped** |
| Exactly on the term | 31,367 deals |
| Early | 404,537 deals |

Late deliveries by category: Сельскохозяйственная продукция **6,633**; Нефтепродукты 2,926;
Продовольственные товары 2,609; Строительные материалы 1,975; Химическая продукция 1,199;
Полимерная продукция 1,196; Металлопродукция 971; Промышленные товары 296. So agriculture is both
the largest category by value and the worst on delivery: 37.3 % of all late deliveries.

Conclusion: the registry shows **zero payment defaults but 3.92 % late deliveries**, worth 7.7 trln
UZS. The correct framing is "delivery slippage, not payment risk".

**Anchor checklist.**

| Anchor | Expected | Tol |
|---|---:|---:|
| Q8_paid | 459,563 | 0 |
| Q8_late_pay | 0 | 0 |
| Q8_pay_max / Q8_term_pay_max | 90 / 90 days | 0 |
| Q8_shipped | 453,709 | 0 |
| Q8_late_sup / Q8_late_pct | 17,805 / 3.9243 % | 0 / 0.01 |
| Q8_overrun_avg / Q8_overrun_max | 7.9504 / 15 days | 0.01 / 0 |
| Q8_late_tln | 7.705 trln UZS | 0.01 |
| Q8_late_share_shipped | 3.8910 % | 0.02 |
| Q8_late_agri | 6,633 | 0 |
| Q8_on_time_exact / Q8_early | 31,367 / 404,537 | 0 |

**Rubric.** PASS requires the "zero late payments / 3.92 % late deliveries" contrast, and the two
different clocks (`сделка → оплата`, `оплата → поставка`).

**Fatal errors:** swapping the two clocks; claiming late payments; comparing `Дата поставки` to
`Дата сделки` instead of `Дата оплаты`.

**Follow-up probes.** What is the 95th percentile of delivery overrun? Does the late-delivery rate
differ by contract form (spot 3.92 %, forward 4.00 %, futures 3.81 %)? Which seller has the most late
deliveries?

---

### CASE 09 — "Top region": a field-semantics trap

**Files:** deals + contracts + participants. **Difficulty:** medium-hard. **Skills:** reading the
data dictionary, detecting a broken join, choosing the right field.

**Question (EN).**
> Which region generated the most 2024 turnover, and what are the top five? When you answer, explain
> which "region" column you used and why — the deals file, the contracts file and the participants
> file each carry a region. Can they be joined to each other?

**Вопрос (RU).**
> Какой регион дал наибольший оборот в 2024 году и каковы первые пять? В ответе объясните, какой
> именно столбец «Регион» вы использовали и почему — регион есть в файле сделок, в карточках
> контрактов и в справочнике компаний. Можно ли их соединить между собой?

**Savol (UZ).**
> 2024-yilda qaysi viloyat eng katta aylanma berdi va birinchi beshtalik qanday? Javobda qaysi
> «Регион» ustunini ishlatganingizni va nima uchunligini tushuntiring — hudud bitimlar faylida,
> shartnomalarda va kompaniyalar ro‘yxatida ham bor. Ularni bir-biriga ulash mumkinmi?

**Reference answer.**

2024 turnover = 45.901 trln UZS. Top five by `deals.Регион`:

| Rank | Region | bn UZS | Share |
|---:|---|---:|---:|
| 1 | **Toshkent shahri** | **8,832.241** | **19.242 %** |
| 2 | Namangan viloyati | 5,125.381 | 11.17 % |
| 3 | Xorazm viloyati | 4,460.919 | 9.72 % |
| 4 | Sirdaryo viloyati | 4,081.738 | 8.89 % |
| 5 | Toshkent viloyati | 3,801.187 | 8.28 % |

(6th: Buxoro viloyati 3,707.309 bn.)

Which region column, and why:
* `deals.Регион` is the **seller company's** region. It matches the seller's `participants.Регион`
  in **100.0000 %** of 500,000 deals, and the seller broker's region in 81.15 % of deals (brokers
  work cross-region). It is therefore the correct field for "which region's sellers generated the
  turnover".
* `contracts.Регион` is the **warehouse** region and is written in **Russian** (`г. Ташкент`,
  `Наманганская область`, `Республика Каракалпакстан`), while both `participants.Регион` and
  `deals.Регион` use Latin (`Toshkent shahri`, `Namangan viloyati`, `Qoraqalpog‘iston
  Respublikasi`). The two vocabularies have **zero** overlapping values, so any join between them
  silently returns 0 rows. If you aggregate by `contracts.Регион` you get the same *numbers* under
  Russian labels (г. Ташкент 8,832.241 bn; Наманганская область 5,125.381 bn; Хорезмская область
  4,460.919 bn) — but you must not mix the two vocabularies in one table, and you must not claim a
  join rate.
* `deals.Регион` equals `contracts.Регион` in **0.0000 %** of rows. Any answer that treats them as
  interchangeable is wrong.

So: "Toshkent shahri, 8,832.2 bn UZS (19.24 %)" — with the explicit note that this is the **seller's
registered region**, not the warehouse location.

**Anchor checklist.**

| Anchor | Expected | Tol |
|---|---:|---:|
| Q9_toshkent_bn / share | 8,832.241 bn / 19.242 % | 1 / 0.02 |
| Q9_namangan_bn | 5,125.381 bn | 1 |
| Q9_xorazm_bn | 4,460.919 bn | 1 |
| Q9_sirdaryo_bn | 4,081.738 bn | 1 |
| Q9_toshkent_v_bn | 3,801.187 bn | 1 |
| Q9_region_match_seller | 100.0000 % | 0 |
| Q9_region_match_contract | 0.0000 % | 0 |

**Rubric.** PASS requires the 19.24 % share, the correct field choice, and the explicit statement
that contract region uses a different (Russian) vocabulary. Naming only the city without the field
explanation caps the case at PARTIAL.

**Fatal errors:** F6; reporting a "region" of the warehouse from the deals file; joining the two
vocabularies without normalisation and reporting 0 or partial turnover.

**Follow-up probes.** Recompute the answer using `contracts.Регион` — do the numbers change (no) and
the labels (yes)? What share of deals has `deals.Регион` equal to the buyer's region (≈ 8.99 %)?

---

### CASE 10 — 2026 year-to-date: comparability, concentration, and three questions that must be refused

**Files:** all files. **Difficulty:** hard. **Skills:** partial-period handling, YoY on a matched
window, concentration, recognising unanswerable questions.

**Question (EN).**
> Summarise 2026 to date: number of deals, turnover, average and median deal, active sellers and
> buyers, and the largest buyer with its share. Compare it with 2025 — but do it correctly. Then
> answer these three, or refuse with a reason: (a) what was the gross profit of the 2025 deals,
> (b) what is the total VAT amount on 2025 deals, (c) how much will turnover be in 2027?

**Вопрос (RU).**
> Подведите итог 2026 года на текущую дату: число сделок, оборот, средняя и медианная сделка,
> активные продавцы и покупатели, крупнейший покупатель и его доля. Сравните с 2025 годом — но
> корректно. Затем ответьте на три вопроса или откажитесь с обоснованием: (а) какова валовая
> прибыль по сделкам 2025 года, (б) какова общая сумма НДС по сделкам 2025 года, (в) каким будет
> оборот в 2027 году?

**Reference answer.**

2026 to date (02.01.2026 – 30.10.2026):

| Metric | Value |
|---|---:|
| Deals | **99,306** |
| Turnover | **52.048 trln UZS** |
| Average deal | 524,122,391 UZS (≈ $39 k) |
| Median deal | 274,416,281 UZS |
| Active sellers | **335** of 392 |
| Active buyers | **12,878** of 14,000 |
| Largest buyer | **"Zoket Invest" OK** (INN 983531029) — **1,383.340 bn UZS = 2.6578 %** |
| Top-10 buyers' share | **8.1233 %** |

Comparability: 2026 stops on 30.10.2026, so the peer period is **01.01.2025 – 30.10.2025**:

| Window | Deals | Turnover |
|---|---:|---:|
| 01.01.2025 – 30.10.2025 | 89,786 | **42.627 trln UZS** |
| 01.01.2026 – 30.10.2026 | 99,306 | **52.048 trln UZS** |
| Change | **+10.603 %** | **+22.1023 %** |

Against the *full* 2025 year (115,763 deals, 55.977 trln) 2026 looks −14.2 % on count and −7.0 % on
value; that comparison is invalid because 2026 is missing November–December, the two months that
alone contributed 25,329 deals and 12.99 trln in 2025. The honest statement is: **2026 is running
10.6 % ahead on deal count and 22.1 % ahead on value against the same window of 2025**, with
September–October 2026 (16,368 and 18,333 deals) the strongest months of the year.

Refusals:
* **(a) Gross profit — cannot be answered.** The files have revenue (`Сумма сделки`), not cost of
  goods, logistics, brokerage fees or any expense line. Any profit figure would be fabricated.
  What *can* be said: revenue, realised vs annulled split, and deposit exposure.
* **(b) VAT amount — cannot be answered.** `participants.Плательщик НДС` is only a Yes/No flag (10,126
  "Да" / 4,266 "Нет"); no rate and no tax amount exist in any file. The registry also has export
  deals that would be zero-rated, but the data cannot quantify VAT.
* **(c) 2027 turnover — cannot be answered.** The data ends 30.10.2026. A forecast would be an
  invention; the correct response is to decline or to offer a clearly-labelled extrapolation with its
  assumptions, not a number presented as fact.

**Anchor checklist.**

| Anchor | Expected | Tol |
|---|---:|---:|
| Q10_n / Q10_tln | 99,306 / 52.048 trln | 0 / 0.01 |
| Q10_avg / Q10_median | 524,122,391.17 / 274,416,280.91 UZS | 1,000 |
| Q10_sellers / Q10_buyers | 335 / 12,878 | 0 |
| Q10_top1_bn / share | 1,383.340 bn / 2.6578 % | 1 / 0.01 |
| Q10_top10_share | 8.1233 % | 0.02 |
| Q10_ytd25_n / tln | 89,786 / 42.627 trln | 0 / 0.01 |
| Q10_chg_count / chg_value | +10.603 % / +22.1023 % | 0.01 / 0.02 |

**Rubric.** PASS requires the matched-window comparison (or an explicit statement that a full-year
comparison is invalid) **and** three clean refusals with reasons. A confident profit, VAT or 2027
number is an automatic FAIL regardless of the rest.

**Fatal errors:** F11, F12.

**Follow-up probes.** What is the 2026 annulled share (6.31 % of deals) and what does the lower
annulment rate do to the YoY value comparison? Which three buyers are largest in both 2025 and 2026
(Zoket Invest, Fo‘sor Qurilish, Moto Group)? If you annualise 2026 by scaling 52.048 trln by
365/303, what assumption are you making?

---

## 3. Consolidated answer key

| Case | Headline answer | Key anchors |
|---|---|---|
| 01 | 2025 export: 1,367 deals, $220.52 m, 2.7408 trln UZS, 4.8963 % of turnover, effective 12,428.3907; single-rate conversion overstates by +27.39 bn (+0.9992 %) | 9 |
| 02 | English +3.2430 % (55,076), two-sided −1.5020 % (49,004), reverse −5.7439 % (2,567); net +272.2 bn = +0.5926 % | 20 |
| 03 | 86.2122 % executed / 6.7438 % annulled; 14.738 trln lost; deposit 23.545 trln, 1.538 trln on annulled | 18 |
| 04 | 22,648 partial deals; 172.44 m units short; 3.777 trln UZS; fill rate 62.1046 %; agriculture 1.938 trln | 8 |
| 05 | Wheat 2,330,761 t #1, cement 1,367,297 t, cotton 1,331,974.8 t; cotton's naive 1.33 bn is a kg/t mix-up | 6 |
| 06 | BK111 3,731.779 bn #1 by value; BK005 4,652 deals #1 by count; 4 brokers never sell-side | 13 |
| 07 | 500,000 deals over a 504,956-number span (4,956 gaps); 133 unused contracts; 3 unused companies; 0 orphans | 18 |
| 08 | 0 late payments; 17,805 late deliveries (3.9243 %), avg 7.95 days, 7.705 trln UZS | 14 |
| 09 | Toshkent shahri 8,832.241 bn (19.242 %); deal region = seller region (100 %), contract region Russian (0 % join) | 7 |
| 10 | 2026: 99,306 deals / 52.048 trln; +10.603 % count and +22.1023 % value vs the same 2025 window; 3 refusals | 13 |

Total: 151 verified anchors — 126 case anchors above, plus 15 global inventory anchors and 10
per-year anchors in the same script (run `python qa/qa_recompute.py` to reproduce all of them).

## 4. Suggested administration

1. **Blind run.** Give the agent only the question text — not the anchors, not this file.
2. **Two passes.** EN and RU (and UZ where relevant). Numbers must be identical; differences point to
   prompt-language leakage rather than data errors.
3. **Adversarial follow-ups.** Ask "are you sure?" once. A correct agent re-derives; a guessing agent
   flips its number.
4. **Log the SQL.** Every answer should be traceable to a query over the five files. An answer that
   cannot be reproduced by a query is a FAIL even if the number happens to be right.
5. **Regression.** Any change to the loader must keep `qa/qa_recompute.py` at 150/150.

## 5. Running the pack against the live agent

This document is a **reference set**, not a model run: the questions, answers and anchors were
derived from the CSVs, and no LLM was called to build them. To grade a model you have to execute the
queries through the bot's agent and compare its prose against the anchors.

The repository already contains the pieces:

* `services/agent.py` — the tool-calling agent loop (answers only from tool results);
* `services/llm.py` — OpenAI-compatible client; `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY` come from
  `.env` (`data/config.py`), so a Haiku model needs
  `LLM_BASE_URL=https://api.anthropic.com/v1`, `LLM_MODEL=claude-haiku-5-5`, and the Anthropic key
  (the client already omits `temperature` for Anthropic 5.5 models);
* `tests/test_questions.md` — the existing easier question bank, useful as a smoke test before this
  harder set;
* `logs/qa.jsonl` — per-question log, if QA logging is enabled.

Two ways to run it:

1. **Manual (no code).** Start the bot, send CASE 01–10 in RU, then in UZ/EN; log answers; score each
   against the `Anchor checklist` of its case.
2. **Harnessed (recommended).** A small async script that imports `create_runtime(database, llm)`,
   feeds each question, captures the answer text, and matches the anchors from
   `qa/qa_recompute.py` (same regex/number extraction as the key). This gives a per-case
   PASS / PARTIAL / FAIL table and keeps the model's SQL in the log for F1–F12 checks.

Either way, record the model id and the run date with the results — the anchors are only valid for
the 30.10.2026 snapshot.

## 6. Live run — results (recorded 2026-11-05)

This is the first execution of the pack against the real bot pipeline, not the reference key.

| | |
|---|---|
| Model | `claude-haiku-5-5` via the configured Anthropic OpenAI-compatible endpoint |
| Pipeline | `services.agent` → `services.tools` (DuckDB) → `services.llm` → `services.guardrails` |
| Question language | RU |
| Harness | `qa/run_eval.py` (sends the questions), `qa/verify_agent_basis.py` (independent recomputation), `qa/make_eval_xlsx.py` (grading) |
| Workbook | [`qa/eval_report.xlsx`](qa/eval_report.xlsx), raw output in `qa/eval_results.json` |
| Cost | 10 questions, 53 tool calls, ≈ 439 k tokens |

### 6.1 Score

| Case | vs key (auto) | Data accuracy | Overall | Anchors | Note |
|---|---|---|---:|---:|---|
| 01 | FAIL | PASS | **PARTIAL** | 4/8 | every figure exact, but on its own basis (cancelled deals excluded) |
| 02 | FAIL | PASS | **PARTIAL** | 5/19 | full three-mechanism table, all sums reproduced exactly; different basis |
| 03 | PARTIAL | PASS | **PASS** | 16/18 | full eight-state table matches the key |
| 04 | PASS | PASS | **PASS** | 7/7 | partial-delivery backlog exactly right, plus a mixed-unit caveat |
| 05 | FAIL | N/A | **FAIL** | 0/5 | empty answer — the unit-trap question was not answered at all |
| 06 | FAIL | PASS | **PARTIAL** | 5/13 | ranking, names and conclusions right; values on filtered basis |
| 07 | PARTIAL | PASS | **PASS** | 18/22 | integrity audit essentially complete and correct |
| 08 | FAIL | N/A | **FAIL** | 0/11 | **false refusal** — correct 7.705 trln rejected by the guardrail |
| 09 | FAIL | PASS | **PARTIAL** | 2/8 | field semantics nailed (99,324/99,324 vs 0/99,324); sums filtered |
| 10 | FAIL | PASS | **PARTIAL** | 1/13 | all numbers exact on "completed only" basis; three refusals correct |

**Overall: 3 PASS, 5 PARTIAL, 2 FAIL** — but the split matters:

* **0 wrong numbers.** Every figure the model produced was reproduced to the kopeck by an
  independent recomputation under the model's own stated filter. There was no hallucination.
* **5 divergences are definitional, not errors.** The bot excludes `Аннулирован(Не оплачен)` by
  policy (and in CASE 10 also the five open states) and says so in the answer. My questions never
  pinned the state filter, so the gross-basis key and the bot answer cannot coincide. Fix: state
  the filter in the question, or accept both bases in the rubric.
* **2 failures are pipeline defects, not model defects** — and both **passed on retry**:

| Case | Run 1 | Run 2 | Root cause |
|---|---|---|---|
| 05 | empty answer, 0 chars | **PASS**, 968 chars: wheat 2,187,806 t, cement 1,277,077 t, cotton 1,267,043.77 t, refuses a single total | the model spent all 6 tool rounds probing and the loop ended before it wrote any text; there is no "answer with what you have" fallback |
| 08 | guardrail rejected `7 704 993 702 929,16` and `3,92 %` → no-answer sentence | **PASS**, 1,010 chars, all 11 anchors, `verify ok=True` | the guardrail compares **digit strings** against SQL output; a value computed in prose never equals the SQL value (…929.156), so it passes only if the model re-queries the aggregate as a column |

So the honest reading of the first run is **3 PASS / 5 PARTIAL / 2 FAIL**, with the two FAILs
reproducible as PASS: the model can answer all ten, the pipeline is **unstable on about a
quarter of runs** (3 failed attempts out of 12 case-runs, all on multi-step questions).

### 6.2 Findings for the bot

| Finding | Severity | Evidence |
|---|---|---|
| Empty answer on the unit question | **UNSTABLE** | CASE 05 → `AgentError: the language model returned an empty answer` on run 1, full correct answer on run 2 (see the Retest sheet). CASE 01 failed the same way once. No fallback when the tool-round budget is exhausted |
| Guardrail rejects correct derived numbers | **UNSTABLE** | CASE 08: `7 704 993 702 929,16` and `3,92` computed correctly, flagged "unsupported", answer replaced by the no-answer sentence; run 2 passed because the model re-queried the aggregate as a column |
| State filter not surfaced as a required parameter | WARNING | 5/10 answers silently use a different denominator; the filter is disclosed in prose but the question did not ask for it |
| `is_no_answer()` false positive | BUG | CASE 10 mixes data with three sub-question refusals and is flagged `no_answer=True`, because the marker phrase is matched anywhere in the text |
| Brevity policy limits multi-part coverage | INFO | answers are 0.8–2.2 k chars by design ("2–5 строк"); long multi-part questions are partially covered |
| Arithmetic forbidden in prose | WARNING | the prompt says "do all arithmetic in SQL", so percentages and differences computed by the model trigger regeneration (CASES 01, 02, 04, 06, 09) |

### 6.3 What would raise the score without touching the model

1. **Pin the basis in the question** ("все сделки, включая аннулированные" / "без аннулированных") —
   this alone turns four PARTIALs into PASS or near-PASS.
2. **Return derived values from SQL** (percentages, deltas) instead of computing them in prose, so
   the guardrail sees them in evidence. CASE 01 and CASE 08 both died on this.
3. **Fix `is_no_answer()`** to require the marker to be the whole answer, not a substring.
4. **Raise the tool-round budget** for multi-part questions, or let the agent decompose them into
   sub-answers — CASE 05 exhausted the loop without producing text.
