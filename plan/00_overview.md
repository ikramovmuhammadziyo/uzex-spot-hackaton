# UZEX AI Hackathon 2026 — Project Plan Overview

## Goal
Build an AI agent as a **Telegram bot** that answers questions about exchange deals in **Russian and Uzbek**, strictly based on the provided CSV data. If the answer is not in the data, the agent must say so explicitly. Hallucination = disqualification.

## Deadlines (Toshkent time)
| When | What |
|---|---|
| **5 Nov, 18:00** | Submit prototype via Google Form (bot link, team members, solution description) |
| 5 Nov, 18:00 → | Commission tests each prototype: 10 questions, ≤90 s per answer |
| 6 Nov | Results & invitations |
| 7–8 Nov, 09:00 | Offline hackathon in Toshkent (top 20 teams) |

## Scoring (100 pts)
| Criterion | Points | How we win it |
|---|---|---|
| Correct answers | 60 | 10 questions × 6 pts — exact numbers/names/codes from data |
| Prototype quality | 20 | Shows evidence ("javob nimaga asoslangan"), understands RU+UZ, fast & convenient |
| Solution description | 20 | Clear write-up of tech stack, methods, and how answers are verified |

## Architecture at a glance
```
User (Telegram, RU/UZ)
   ↓
Telegram Bot (Python, aiogram)
   ↓
LLM Orchestrator (tool-calling agent)
   ├── Query Engine → DuckDB (500k deals + reference tables)
   ├── Calculator (deterministic, never LLM math)
   └── Guardrails (no-data → explicit "no answer" message)
   ↓
Answer in the question's language, with source evidence
```

## Plan documents
| File | Contents |
|---|---|
| [01_requirements.md](01_requirements.md) | Full rules summary, scoring, constraints |
| [02_data_layer.md](02_data_layer.md) | Data schema, cleaning, DuckDB loading, computed fields |
| [03_architecture.md](03_architecture.md) | Bot + LLM + tool-calling design |
| [04_query_engine.md](04_query_engine.md) | Tools/functions the LLM can call, SQL patterns |
| [05_guardrails.md](05_guardrails.md) | Anti-hallucination & verification strategy |
| [06_telegram_bot.md](06_telegram_bot.md) | Bot implementation & deployment |
| [07_testing.md](07_testing.md) | Test question bank (RU/UZ) with ground-truth answers |
| [08_timeline.md](08_timeline.md) | Hour-by-hour plan until 5 Nov 18:00 |
| [09_submission.md](09_submission.md) | Google Form contents, solution description draft |
