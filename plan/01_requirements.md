# 01 — Requirements (from hackathon rules)

Source: `hackathon_rules.html` (Saralash bosqichi — UZEX AI Hackathon 2026).

## Task
> Birja bitimlari haqidagi savollarga aniq va faqat maʼlumotlar asosida javob beradigan AI-agent yarating.

Build an AI agent that answers questions about exchange deals:
- Answers must be **correct and data-based**: exact numbers, names, codes.
- If the data has no answer, the agent must **openly say so**, not invent one.
- The approach is free — any tools, including LLMs and AI assistants.

## Interface
- **Telegram bot** (chosen) or web service.
- Must work for the commission **without installation or registration**.
- Must be **always running** from submission until checked.

## Languages
- Questions in **Russian and Uzbek**.
- Answer in the **same language as the question**.

## Evaluation procedure
- Commission asks **10 questions** about the data, in RU or UZ.
- **≤ 90 seconds** per answer.
- Questions are not announced in advance.
- If the agent invents an answer where data has none → **team disqualified**.

## Scoring
| Criterion | Points |
|---|---|
| Correct answers (10 × 6) | 60 |
| Prototype quality — visible evidence, RU+UZ understanding, convenient & fast | 20 |
| Solution description — technologies, methods, verification of answers | 20 |

## Rules
- Team of up to 3 people.
- Don't share code/prototype with other teams (similarity is checked).
- Prototype must stay running as a Telegram bot or web app.
- Can update the prototype until 5 Nov 18:00 (resubmit the form). No changes after.

## Data facts (from README)
- All data is fictional (companies, INN, brokers, contracts, deals, prices, USD rate). Format mirrors spot.uzex.uz public registry.
- 500,000 deals: 03.01.2022 → 30.10.2026 (2022: 84,299 · 2023: 93,985 · 2024: 106,647 · 2025: 115,763 · 2026: 99,306).
- Contracts: 6,616 · Participants: 14,392 · Brokers: 120 · USD rates: daily.
- CSV UTF-8, comma separator, quoted values, dates ДД.ММ.ГГГГ, Tashkent time.
- Deal states as of end of day 30.10.2026.
