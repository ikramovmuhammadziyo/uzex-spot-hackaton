# 05 — Guardrails & Anti-Hallucination

Disqualification rule: if the agent invents an answer where the data has none → team is out. This document is the defense.

## Layer 1 — Prompt-level
- System prompt: "Use ONLY tool results. Never estimate, never use outside knowledge."
- Explicit no-answer templates:
  - RU: «В данных реестра ответа на этот вопрос нет.»
  - UZ: «Maʼlumotlar reyestrida bu savolga javob yoʻq.»
- Instruct LLM to double-check by running a confirming query for critical numbers.

## Layer 2 — Deterministic computation
- ALL arithmetic happens in SQL/DuckDB, never in the LLM head.
- No "approximately" — tool returns exact decimals; formatting only (spaces for thousands) in the output layer.

## Layer 3 — Post-generation verification (`guardrails.py`)
1. Extract every number ≥ 4 digits from the final answer.
2. Check each appears in at least one tool result from this conversation turn (as raw or formatted-with-spaces variant).
3. If a number is NOT traceable → regenerate once with a stricter prompt; if still untraceable → send the no-answer template.
4. Same check for company names / INN mentioned: must appear in tool outputs.

## Layer 4 — Evidence requirement
- Every answer includes an "Основание / Asos" line: filters + identifiers used.
- If no evidence can be attached, answer is not sent — replaced by no-answer template.

## Layer 5 — Test bank (see 07)
- Trick questions with NO answer in data (e.g. real company names, products not in registry, dates outside 2022–2026) — agent must refuse correctly 100% of the time. This is pass/fail.

## Edge cases to handle
| Case | Correct behaviour |
|---|---|
| Question about real-world company | No-answer (data is fictional) |
| Product name spelled differently | Use `search_products`, answer for the matched registry name, note the match |
| Currency ambiguity | Report both native currency and UZS equivalent |
| State ambiguity ("сколько сделок") | Give total + note how many Исполнен/Аннулирован |
| Future/out-of-range dates | No-answer or nearest in-range, stated clearly |
