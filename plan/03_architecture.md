# 03 — Architecture

## Component diagram
```
┌────────────────────────────────────────────────────┐
│  Telegram user (RU / UZ questions)                 │
└──────────────┬─────────────────────────────────────┘
               │ Telegram Bot API (long polling)
┌──────────────▼─────────────────────────────────────┐
│  bot.py  (aiogram 3)                               │
│  - detect language (ru/uz)                         │
│  - typing indicator, 90 s budget guard             │
│  - format answer + evidence                        │
└──────────────┬─────────────────────────────────────┘
               │
┌──────────────▼─────────────────────────────────────┐
│  agent.py  (LLM orchestrator)                      │
│  - system prompt: data-only answers, RU/UZ         │
│  - tool-calling loop (max ~4 iterations)           │
│  - never computes numbers itself                   │
└──────┬──────────────────────┬──────────────────────┘
       │ tools                │
┌──────▼─────────┐   ┌────────▼─────────────┐
│ query_engine.py│   │ guardrails.py        │
│ run_sql()      │   │ - verify numbers in  │
│ search tools   │   │   final answer exist │
│ (see 04)       │   │   in tool outputs    │
└──────┬─────────┘   │ - empty result →     │
       │             │   "no answer" path   │
┌──────▼─────────┐   └──────────────────────┘
│ uzex.duckdb    │
│ deals_enriched │
└────────────────┘
```

## Technology choices
| Layer | Choice | Why |
|---|---|---|
| Bot | Python + **aiogram 3**, long polling | No public URL needed; runs anywhere; zero frontend |
| DB | **DuckDB** (embedded) | Fast analytics over 500k rows; single file; SQL the LLM knows well |
| LLM | Claude / GPT with tool use | Allowed by rules; strong RU+UZ; reliable function calling |
| Deploy | VPS or any always-on machine running `python bot.py` (systemd / pm2 / tmux) | Long polling needs no domain, no TLS, no ports open |

## Request flow (with timing budget ≤ 90 s)
1. Receive message → detect language → send "typing…".
2. LLM call #1 with system prompt + tools. Typical: 1–3 tool calls (SQL).
3. Execute SQL via DuckDB (sub-second for 500k rows).
4. LLM composes answer citing numbers + evidence (deal numbers, row counts, filters used).
5. Guardrail check (see 05) → send.
6. Total target: **10–30 s** typical; hard timeout 75 s → fallback message.

## Answer format
```
📊 Ответ: <точный ответ — число/имя/код>

Основание: <какие данные использованы: таблица, фильтры, № сделок>
— e.g. "Сделка №185158 от 02.01.2023, сумма 131 895 492 сум"
```
Uzbek version mirrors the structure. Evidence line = easy 20 quality points.

## Failure paths
| Case | Behaviour |
|---|---|
| No data matches | "В данных реестра ответа нет." / "Maʼlumotlarda javob yoʻq." (never guess) |
| Ambiguous question | Answer with the most reasonable interpretation + state assumption |
| SQL error | LLM retries once; then honest error message |
| Timeout | "Не успел посчитать, попробуйте переформулировать" |
