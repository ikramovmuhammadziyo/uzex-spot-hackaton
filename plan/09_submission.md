# 09 — Submission (Google Form, до 5 Nov 18:00)

## Form fields
1. **Prototype link** — `t.me/<bot_username>` (bot must be running and open to everyone).
2. **Team members** — full names, up to 3 people.
3. **Solution description** — see draft below.
4. Team leader name + phone (results go to this number).

## Solution description — draft (worth 20 points)

> **Архитектура.** Telegram-бот (Python, aiogram) → LLM-оркестратор с function-calling → аналитическая БД DuckDB, загруженная из всех CSV реестра (500 000 сделок, контракты, участники, брокеры, курс USD).
>
> **Как получается ответ.** LLM не генерирует числа сам: он переводит вопрос (RU/UZ) в SQL-запрос к данным, получает точные строки и только из них формирует ответ. Вся арифметика (объём = Количество × Лот, цена = Сумма ÷ объём, пересчёт USD→сум по курсу на дату сделки) выполняется детерминированно в SQL.
>
> **Проверка ответов (anti-hallucination).** После генерации каждое число и каждое название в ответе сверяются с результатами SQL-запросов этого же диалога; неподтверждённый ответ не отправляется. Если данных нет, бот честно отвечает «В данных реестра ответа нет» / «Maʼlumotlarda javob yoʻq» — на языке вопроса.
>
> **Качество.** Каждый ответ содержит блок «Основание»: фильтры и идентификаторы (№ сделки, контракта, ИНН), на которых основан ответ. Бот автоматически определяет язык вопроса (русский/узбекский) и отвечает на нём же. Типичное время ответа — 10–30 секунд.
>
> **Обработка неоднозначностей.** Названия товаров нормализуются («1 сорт» = «1-сорта»), состояния сделок учитываются по их смыслу (аннулированные не считаются состоявшимися), экспортные суммы приводятся и в долларах, и в сумах.

## Checklist before submitting
- [ ] Bot username/link correct and public
- [ ] Bot answers a stranger (tested from another account)
- [ ] Description finalized (RU, ~150–200 words)
- [ ] Names/phone double-checked
- [ ] Submitted ≤ 17:45, confirmation received
