# 08 — Timeline (4 Nov evening → 5 Nov 18:00)

Current time: 4 Nov, ~22:00. Deadline: 5 Nov, 18:00. Budget: ~20 hours.

## Night session (4 Nov, 22:00 → 5 Nov ~02:00)
| Time | Task | Output |
|---|---|---|
| 22:00–23:00 | Data layer: `load_data.py`, DuckDB build, validation (500,000 rows, joins) | `uzex.duckdb` + sanity report |
| 23:00–00:00 | Compute ground-truth answers for test bank (SQL by hand) | filled `07_testing.md` |
| 00:00–01:30 | Agent core: system prompt + `run_sql` tool + LLM loop | working CLI agent |
| 01:30–02:00 | First smoke test: 10 questions via CLI | gap list |

## Morning (5 Nov, 09:00 → 13:00)
| Time | Task | Output |
|---|---|---|
| 09:00–10:00 | Search tools (products/companies fuzzy match) + usd_rate tool | `tools.py` complete |
| 10:00–11:00 | Guardrails: number traceability, no-answer path | `guardrails.py` |
| 11:00–12:00 | Telegram bot wrapper (aiogram, long polling) | bot answers in Telegram |
| 12:00–13:00 | Bilingual pass: test all bank questions in RU **and** UZ | bilingual pass report |

## Afternoon (5 Nov, 13:00 → 18:00)
| Time | Task | Output |
|---|---|---|
| 13:00–14:30 | Full test-bank regression; fix failures | ≥ 90% pass |
| 14:30–15:30 | Deploy to always-on machine + systemd + monitoring | live bot, stable |
| 15:30–16:30 | Trick-question gauntlet (must be 100% refusal) | disqualification-proof |
| 16:30–17:15 | Write solution description (20 pts!) | form text ready |
| 17:15–17:45 | Final end-to-end check from a fresh Telegram account | confidence |
| **17:45** | **Submit Google Form** (buffer 15 min) | ✅ done |

## Contingency
- If LLM tool-calling is unstable → fallback: intent-classifier + fixed SQL templates (covers ~80% of question types, still data-grounded).
- If deployment machine fails → run bot from dev laptop via tmux, keep it plugged in.
- If time runs out on polish: correctness > evidence line > bilingual niceties. The 60 pts for correct answers dominate.
