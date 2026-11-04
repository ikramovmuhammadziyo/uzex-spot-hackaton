# 07 — Testing

## Method
1. Write ground-truth SQL for every test question by hand.
2. Ask the bot in RU and UZ variants.
3. Compare numbers exactly. Any mismatch → fix prompt/tool, retest all.

## Question bank — categories (fill in ground truth after data layer is built)

### A. Aggregates
| # | RU | UZ |
|---|---|---|
| A1 | Сколько всего сделок заключено в 2024 году? | 2024-yilda jami nechta bitim tuzilgan? |
| A2 | Какая компания продала на наибольшую сумму в 2025? | 2025-yilda eng katta summaga sotgan kompaniya qaysi? |
| A3 | Общий объём торгов в сумах за 2023 год? | 2023-yil uchun jami savdo hajmi so‘mda? |

### B. Lookups
| # | RU | UZ |
|---|---|---|
| B1 | Найди сделку №185158 — кто продавец и покупатель? | 185158-raqamli bitimni top — sotuvchi va xaridor kim? |
| B2 | Что за компания с ИНН 986932945? | STIR 986932945 qanday kompaniya? |
| B3 | Какие товары продаёт компания "..." ? | "..." kompaniyasi qanday tovarlar sotadi? |

### C. Price/volume analytics
| # | RU | UZ |
|---|---|---|
| C1 | Средняя цена за тонну каустической соды в 2023? | 2023-yilda kaustik soda tonnasi o‘rtacha narxi? |
| C2 | Самая дорогая сделка 2026 года в пересчёте на сумы? | 2026-yil eng qimmat bitim so‘mda qancha? |
| C3 | Сколько тонн хлопка продано в Ташкентской области? | Toshkent viloyatida necha tonna paxta sotilgan? |

### D. States & terms
| # | RU | UZ |
|---|---|---|
| D1 | Сколько сделок аннулировано из-за неоплаты в 2025? | 2025-yilda to‘lanmaganligi uchun nechta bitim bekor qilingan? |
| D2 | Доля исполненных сделок по фьючерсам? | Fyuchers bitimlarining bajarilgan ulushi? |

### E. Export/currency
| # | RU | UZ |
|---|---|---|
| E1 | Сумма экспортных сделок в долларах в 2024? | 2024-yilda eksport bitimlari dollarda qancha? |
| E2 | Та же сумма в сумах? | Xuddi shu summa so‘mda? |

### F. Brokers
| # | RU | UZ |
|---|---|---|
| F1 | Через какого брокера прошло больше всего сделок? | Eng ko‘p bitim qaysi broker orqali o‘tgan? |

### G. Trick questions — MUST refuse (pass/fail)
| # | Question | Expected |
|---|---|---|
| G1 | Сколько сделок заключил "Узавтосаноат"? | No-answer (not in data) |
| G2 | Какой курс доллара был 15.06.2030? | No-answer (out of range) |
| G3 | Savdo bitimlari 2021-yilda qanday bo‘lgan? | No-answer (data starts 2022) |
| G4 | Кто выиграл последние торги по нефти? | No-answer if no oil products in data |
| G5 | Какая погода была в день сделки №1? | No-answer (not in data) |

## Latency test
- 10 random questions; p95 must be < 30 s (budget 90 s).

## Regression rule
After any prompt/tool change, re-run the entire bank. Keep results in a table with pass/fail per question.
