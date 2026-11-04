# UZEX Spot Telegram Bot

AI agent for the UZEX Spot exchange registry. It answers questions in **Russian
and Uzbek**, and every number, company name, INN, broker code and date in the
answer is taken from the supplied CSV registry — never from the model's memory.

- Telegram interface: aiogram 3 (long polling, no web server or domain needed).
- Analytics database: DuckDB, built from the CSV files in the repository.
- LLM: any OpenAI-compatible `/chat/completions` endpoint with tool calling.
- Anti-hallucination: SQL-only arithmetic plus deterministic post-generation
  verification of every significant value.

## How it works

```
Telegram user (RU / UZ)
        │
        ▼
aiogram handlers ── language detection, per-chat lock, 75 s budget, typing
        │
        ▼
Agent (services/agent.py) ── system prompt + conversation history
        │
        ├── LLM (OpenAI-compatible API, tool calling)
        │
        ├── run_sql(query)          read-only DuckDB SELECT, max 100 rows
        ├── search_products(term)   fuzzy product lookup (1 сорт / 1-сорта)
        ├── search_company(term)    company by INN/name, broker by code/name
        └── usd_rate(date)          exact USD→UZS rate for one date
        │
        ▼
Guardrails (services/guardrails.py)
  every significant number/date/INN/broker code/company name must appear in a
  tool result from this turn → otherwise one regeneration → otherwise the
  exact no-answer sentence
        │
        ▼
Answer + evidence line ("Основание" / "Asos")
```

The database is opened **read-only**. `run_sql` accepts exactly one
`SELECT`/`WITH` statement, blocks writes, pragmas, attachments and file-reading
functions, caps output at 100 rows and interrupts queries after 15 seconds.
All totals, averages, conversions and rankings are computed in SQL.

## Requirements

- Python 3.12 (3.11+ should work)
- ~1 GB free disk space for the DuckDB file
- Outbound HTTPS access to Telegram and to your LLM provider
- A bot token from [@BotFather](https://t.me/BotFather)

## Quick start

```bash
git clone https://github.com/ikramovmuhammadziyo/uzex-spot-hackaton
cd uzex-spot-hackaton

python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

pip install -r requirements.txt

# Build data/uzex.duckdb from the CSV files (~1–3 minutes, 500k deals).
python utils/db_api/load_data.py

# Create the environment file and fill in the secrets.
cp .env.dist .env          # Windows: copy .env.dist .env

python app.py
```

On startup the bot logs the database row counts and the LLM configuration, sets
the command menu and begins long polling. Send `/start` to the bot in Telegram.

The DuckDB file `data/uzex.duckdb` is generated locally and is **not** committed
to git. Rebuild it on every machine or server that runs the bot.

## Configuration

All settings live in `.env` (see `.env.dist` for the full template).

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `BOT_TOKEN` | yes | — | Telegram bot token from @BotFather |
| `LLM_API_KEY` | yes | — | API key of the OpenAI-compatible provider |
| `LLM_MODEL` | yes | `gpt-4o-mini` | Model name, exactly as the provider expects |
| `LLM_BASE_URL` | yes | `https://api.openai.com/v1` | Base URL **without** `/chat/completions` |
| `ADMINS` | no | empty | Comma-separated Telegram user IDs for startup/`/health` |
| `DB_PATH` | no | `data/uzex.duckdb` | Path to the DuckDB file |
| `LLM_TEMPERATURE` | no | `0` | Keep at 0 for deterministic answers |
| `LLM_MAX_TOKENS` | no | `1600` | Maximum answer length |
| `LLM_TIMEOUT_SECONDS` | no | `60` | Per-request LLM timeout |
| `LLM_MAX_TOOL_ROUNDS` | no | `6` | Tool-calling iterations per question |
| `AGENT_TIMEOUT_SECONDS` | no | `75` | Whole-question budget (hackathon limit is 90 s) |
| `MAX_HISTORY_TURNS` | no | `8` | Follow-up context messages kept per chat |
| `HISTORY_TTL_SECONDS` | no | `1800` | Context expires after 30 minutes |
| `RATE_LIMIT_SECONDS` | no | `1.5` | Per-user flood guard |
| `LOG_LEVEL` | no | `INFO` | Console/file log level |
| `QA_LOG_PATH` | no | `logs/qa.jsonl` | JSONL log of questions/answers (user IDs hashed) |

### LLM provider examples

The client only needs an OpenAI-compatible API with tool calling.

| Provider | `LLM_BASE_URL` | Example `LLM_MODEL` |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini`, `gpt-4.1-mini` |
| OpenRouter | `https://openrouter.ai/api/v1` | `openai/gpt-4o-mini`, `anthropic/claude-3.5-sonnet` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| Together | `https://api.together.xyz/v1` | `meta-llama/Llama-3.3-70B-Instruct-Turbo` |
| Ollama (local) | `http://localhost:11434/v1` | `qwen2.5:14b` (key can be any non-empty string) |

For OpenRouter you may need extra headers; set them as JSON:

```env
LLM_EXTRA_HEADERS={"HTTP-Referer":"https://github.com/ikramovmuhammadziyo/uzex-spot-hackaton","X-Title":"UZEX Spot Bot"}
```

Use a model that reliably supports **function/tool calling**. Small models that
ignore tools will trigger the forced-tool retry and then the no-answer sentence.

## Bot commands

| Command | Behaviour |
|---|---|
| `/start` | Bilingual greeting, examples and language buttons |
| `/help` | How to ask, examples, no-answer policy |
| `/lang ru` | Always answer in Russian |
| `/lang uz` | Always answer in Uzbek |
| `/lang auto` | Detect the language from each message (default) |
| `/reset` | Clear the follow-up context for this chat |
| `/health` | Admin-only: DB row counts, LLM config, uptime |

Plain text messages are treated as questions. Follow-ups are supported within
the context window: "А та же сумма в сумах?" reuses the previous filters but
re-runs the SQL.

## Answer rules

- The prompt contains the full DuckDB schema, deal-state semantics, unit and
  average-price rules, and the no-answer policy.
- **No-answer sentences** (exact):
  - RU: `В данных реестра ответа на этот вопрос нет.`
  - UZ: `Maʼlumotlar reyestrida bu savolga javob yoʻq.`
- Cancelled deals (`Аннулирован(Не оплачен)`) are excluded from turnover,
  "sold" and average-price calculations; the answer states that filter.
- Plain "how many deals" questions report the total and a state breakdown.
- Every normal answer ends with an evidence line naming the DuckDB table(s),
  filters, and identifiers/row count. Raw SQL is not shown to users.
- A typical answer takes 5–25 seconds; the hard budget is 75 seconds.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

- `tests/test_guardrails.py` — number/date/name verification and no-answer logic.
- `tests/test_tools.py` — SQL safety, real-DB queries, fuzzy product/company search.
- `tests/test_language.py` — RU/UZ detection.
- `tests/test_agent.py` — fake-LLM tool loop, forced tools, regeneration.
- `tests/test_questions.md` — ground-truth question bank (RU/UZ) with SQL and
  expected values for manual regression.

Database-backed tests are skipped automatically if `data/uzex.duckdb` is absent.

## Deployment

### Linux (systemd)

```ini
[Unit]
Description=UZEX Spot Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=uzex
WorkingDirectory=/opt/uzex-spot
EnvironmentFile=/opt/uzex-spot/.env
ExecStart=/opt/uzex-spot/.venv/bin/python /opt/uzex-spot/app.py
Restart=always
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now uzex-bot
journalctl -u uzex-bot -f
```

The bot uses long polling, so no open ports or TLS certificate are required.
Keep the process running from submission until the commission finishes testing
(`Restart=always` covers crashes; add a watchdog if the host reboots).

On Windows, run it as a scheduled task or with NSSM. Activate the venv or use
the full path to `.venv\Scripts\python.exe`.

### Checklist before submitting

1. `.env` contains a valid `BOT_TOKEN` and `LLM_API_KEY`.
2. `data/uzex.duckdb` exists on the server and startup logs `database ready`.
3. `/start`, `/help`, `/lang ru|uz|auto` work from a fresh Telegram account.
4. Run 5–10 questions from `tests/test_questions.md` in both languages.
5. Confirm a trick question (G1–G5) returns the exact no-answer sentence.
6. Confirm an answer arrives in under 90 seconds and ends with an evidence line.
7. The bot is reachable by anyone (no private-mode restrictions).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `BOT_TOKEN is not set` | `.env` is missing or the token line is empty |
| `database file not found` | Run `python utils/db_api/load_data.py` first |
| `LLM_API_KEY is not configured` | Fill `LLM_API_KEY` in `.env` |
| HTTP 401 from the LLM | Wrong API key for the selected provider |
| HTTP 404 from the LLM | Wrong `LLM_BASE_URL` or model name; base URL must end at `/v1`, not `/chat/completions` |
| Bot replies with the no-answer sentence too often | Model is not calling tools, or guardrails reject its draft; check `logs/bot.log` and try a stronger tool-calling model |
| `query timed out` | Narrow the SQL/period; the DB is 500k deals |
| Answers in the wrong language | Use `/lang ru` or `/lang uz` to pin the language |
| `TelegramConflictError` | Another bot instance is polling with the same token |

## Logs and privacy

- `logs/bot.log` — rotating application log (5 MB × 5).
- `logs/qa.jsonl` — one JSON object per question: language, latency, tool calls,
  tables, SQL, row counts, guardrail status. Telegram user IDs are hashed.
- `.env` and the DuckDB file are git-ignored. Never commit real API keys.
