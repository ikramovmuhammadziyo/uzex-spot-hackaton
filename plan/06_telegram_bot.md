# 06 — Telegram Bot

## Why bot over web
- No frontend, no hosting/domain/TLS — long polling works from any machine.
- Commission needs zero installation/registration (rules satisfied).
- Submit just the bot link (`t.me/<botname>`) in the Google Form.

## Setup
1. Create bot via @BotFather → token.
2. Repo layout:
```
bot/
  bot.py            # aiogram entry point (long polling)
  agent.py          # LLM orchestrator + tool loop
  tools.py          # run_sql, search_products, search_company, usd_rate
  guardrails.py     # number/name traceability checks
  prompts.py        # system prompt (schema + rules + RU/UZ templates)
  config.py         # tokens via env vars
data/
  uzex.duckdb       # built by scripts/load_data.py
scripts/
  load_data.py      # CSV → DuckDB
tests/
  test_questions.md # RU/UZ bank with ground truth
```

## Bot behaviour
| Feature | Detail |
|---|---|
| `/start` | Short bilingual greeting: what the bot can do, example questions in RU+UZ |
| Language | Auto-detect from the message (Cyrillic vs Uzbek Latin + keywords); reply in same language |
| Long answers | Split into multiple messages ≤ 4000 chars; numbers formatted with space thousands |
| Typing | `send_chat_action("typing")` refreshed while processing |
| Timeout | 75 s internal limit → polite retry message (rules allow 90 s) |
| Errors | Honest "не смог обработать" + suggestion to rephrase; never a fabricated answer |
| Logging | Log every Q&A pair to file — useful for the 20-pt solution description and debugging |

## Deployment (must stay up from 5 Nov 18:00 through checking)
- **Simplest reliable**: always-on machine (VPS or home PC) + `tmux`/`systemd` + auto-restart.
- `systemd` unit with `Restart=always`; token in env var.
- Health: cron pings the bot every 10 min; alert to team Telegram if down.
- Fallback: second machine ready to start with same token (only one poller at a time).

## Pre-submission checklist
- [ ] Answers 10/10 test-bank questions correctly in RU and UZ
- [ ] Refuses all trick questions
- [ ] p95 latency < 30 s
- [ ] Runs unattended for 24 h without crash
- [ ] Google Form submitted before 18:00 with t.me link
