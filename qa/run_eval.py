"""Run the 10 hard QA cases through the bot's real agent and score them against the answer key.

Usage:
    .venv\\Scripts\\python.exe qa/run_eval.py            # run all cases
    .venv\\Scripts\\python.exe qa/run_eval.py 3 5        # only cases 3 and 5

Writes qa/eval_results.json (raw answers + metrics) and qa/eval_report.xlsx (graded workbook).

The agent is the production pipeline: services.database -> services.tools SQL -> services.llm ->
services.guardrails, i.e. exactly what the Telegram bot runs. Nothing is hard-coded or hinted.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import hashlib
import logging
import os
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from data import config  # noqa: E402
from services.agent import Agent  # noqa: E402
from services.database import Database  # noqa: E402
from services.llm import LLMClient  # noqa: E402

from qa.anchors_data import EXPECTED  # noqa: E402

# ---------------------------------------------------------------------------
# the ten cases (questions are the RU wording from QA_10_HARD_TESTS.md)
# ---------------------------------------------------------------------------
CASES = [
    dict(
        id="01",
        title="Экспорт 2025 и конвертация по курсу дня сделки",
        question=(
            "Оцените экспортный сегмент биржи за 2025 год: сколько экспортных сделок, какова их "
            "сумма в долларах, сколько это в сумах, какую долю оборота 2025 года это составляет и "
            "какой эффективный курс сум/доллар из этого следует? Затем покажите, что получится, "
            "если пересчитать весь сегмент по курсу 12 552,58 на 31.12.2025 — какова ошибка в "
            "сумах и в процентах?"
        ),
        anchors=[
            "Q1_2025_export_n", "Q1_2025_export_usd", "Q1_2025_export_uzs", "Q1_share_value_pct",
            "Q1_eff_rate", "Q1_at_ye_rate", "Q1_error_vs_ye", "Q1_error_pct",
        ],
    ),
    dict(
        id="02",
        title="Механизмы торгов 2024: отклонение цены от стартовой",
        question=(
            "Только за 2024 год сравните три механизма торгов. По каждому (Английский аукцион, "
            "Двусторонний аукцион, Обратный аукцион) дайте число сделок, среднее и медианное "
            "отклонение фактической цены за единицу от стартовой в процентах, наблюдавшийся "
            "диапазон, сколько сделок закрылось ровно по стартовой цене и совокупную премию или "
            "дисконт в сумах. Затем назовите чистый эффект механизма торгов на оборот 2024 года."
        ),
        anchors=[
            "Q2_eng_n", "Q2_eng_avg", "Q2_eng_med", "Q2_eng_max", "Q2_eng_at_start", "Q2_eng_prem_bn",
            "Q2_dbl_n", "Q2_dbl_avg", "Q2_dbl_med", "Q2_dbl_at_start", "Q2_dbl_prem_bn",
            "Q2_rev_n", "Q2_rev_avg", "Q2_rev_med", "Q2_rev_min", "Q2_rev_at_start", "Q2_rev_prem_bn",
            "Q2_net_prem_bn", "Q2_net_pct",
        ],
    ),
    dict(
        id="03",
        title="Восемь состояний сделок, аннулированные и залог",
        question=(
            "Дайте полное распределение восьми состояний сделок: количество, доля сделок, "
            "стоимость в сумах и доля стоимости. Какая часть оборота не состоялась и какая её часть "
            "покрыта договорным залогом? Какие состояния могут существовать только потому, что "
            "выгрузка сделана 30.10.2026, и что это значит для сравнений год к году?"
        ),
        anchors=[
            "Q3_done_n", "Q3_done_pct_n", "Q3_done_tln", "Q3_done_pct_v",
            "Q3_ann_n", "Q3_ann_pct_n", "Q3_ann_tln", "Q3_ann_pct_v",
            "Q3_part_n", "Q3_part_tln", "Q3_paid_n", "Q3_signed_n", "Q3_wait_n",
            "Q3_new_n", "Q3_unsigned_n",
            "Q3_deposit_all_tln", "Q3_deposit_ann_tln", "Q3_deposit_ann_share",
        ],
    ),
    dict(
        id="04",
        title="Частичная поставка: недопоставленный объём и стоимость",
        question=(
            "Состояние «Исполнен(Частично)» означает, что покупатель оплатил, а товар поставлен "
            "лишь частично. Оцените этот хвост: сколько сделок, сколько лотов и сколько физических "
            "единиц не поставлено, сколько это стоит в сумах по цене сделки за единицу, каков "
            "совокупный коэффициент поставки, на какую категорию товара приходится основная часть "
            "и какая отдельная сделка даёт наибольший недопоставленный объём?"
        ),
        anchors=[
            "Q4_deals", "Q4_und_lots", "Q4_und_vol", "Q4_tln", "Q4_fill_pct",
            "Q4_agri_tln", "Q4_max_und_lots",
        ],
    ),
    dict(
        id="05",
        title="Крупнейший физический объём 2026: ловушка единиц",
        question=(
            "Какой товар в 2026 году имел наибольший физический объём? Назовите тройку лидеров с "
            "цифрами, объясните, как именно вы привели их к сопоставимому виду, и скажите, можно ли "
            "вообще назвать единую цифру «общий физический объём за 2026 год»."
        ),
        anchors=["Q5_wheat_t", "Q5_cement_t", "Q5_cotton_t", "Q5_cotton_kg", "Q5_units_2026"],
    ),
    dict(
        id="06",
        title="Рейтинг брокеров 2025: количество против суммы",
        question=(
            "Постройте рейтинг брокеров со стороны продавца за 2025 год. Кто входит в топ-5 по "
            "сумме в сумах (с количеством сделок и долями), кто внизу, и совпадает ли лидер по "
            "количеству сделок с лидером по сумме? Какие брокеры вообще ни разу не выступали за "
            "продавца и сколько из 120 контор были активны на стороне продавца в 2025 году?"
        ),
        anchors=[
            "Q6_bk111_n", "Q6_bk111_bn", "Q6_bk111_share", "Q6_bk106_n", "Q6_bk106_bn",
            "Q6_bk102_bn", "Q6_bk047_bn", "Q6_bk005_n", "Q6_bk005_bn",
            "Q6_bk031_n", "Q6_bk031_bn", "Q6_never_seller", "Q6_active_2025",
        ],
    ),
    dict(
        id="07",
        title="Аудит целостности реестра",
        question=(
            "Проведите аудит реестра. Укажите: общее число сделок и диапазон номеров с числом "
            "пропущенных номеров; сколько контрактов заведено, сколько использовано и каково "
            "распределение неиспользованных по валюте; сколько компаний зарегистрировано, сколько "
            "реально торгует и сколько из них продавцы и покупатели; сколько брокеров и сколько ни "
            "разу не выступали за продавца; покрытие таблицы курса и монотонен ли курс; есть ли "
            "«осиротевшие» сделки; и число различных торговых дней."
        ),
        anchors=[
            "G_deals", "Q7_span", "Q7_gaps", "G_contracts", "G_contracts_used", "G_contracts_unused",
            "Q7_unused_uzs", "Q7_unused_usd", "G_participants", "G_sellers", "G_buyers",
            "Q7_p_unused", "G_brokers", "Q6_never_seller", "Q7_rate_days", "Q7_rate_missing",
            "Q7_rate_min", "Q7_rate_max", "Q7_rate_down_days", "Q7_orphans", "Q7_deal_dates",
            "Q7_weekend",
        ],
    ),
    dict(
        id="08",
        title="Платёжная и поставочная дисциплина",
        question=(
            "Используя «Срок оплаты» (дней от даты сделки) и «Срок поставки» (дней от даты оплаты), "
            "оцените дисциплину: сколько сделок оплачено, сколько оплачено с нарушением срока, "
            "каков максимальный разрешённый и фактический срок оплаты; сколько поставлено, сколько "
            "поставлено с нарушением, на сколько дней в среднем и максимум, какая стоимость "
            "затронута и какая категория хуже всех?"
        ),
        anchors=[
            "Q8_paid", "Q8_late_pay", "Q8_pay_max", "Q8_term_pay_max", "Q8_shipped",
            "Q8_late_sup", "Q8_late_pct", "Q8_overrun_avg", "Q8_overrun_max",
            "Q8_late_tln", "Q8_late_agri",
        ],
    ),
    dict(
        id="09",
        title="Топ-регион 2024: семантика поля",
        question=(
            "Какой регион дал наибольший оборот в 2024 году и каковы первые пять? В ответе "
            "объясните, какой именно столбец «Регион» вы использовали и почему — регион есть в "
            "файле сделок, в карточках контрактов и в справочнике компаний. Можно ли их соединить "
            "между собой?"
        ),
        anchors=[
            "Q9_toshkent_bn", "Q9_toshkent_share", "Q9_namangan_bn", "Q9_xorazm_bn",
            "Q9_sirdaryo_bn", "Q9_toshkent_v_bn", "Q9_region_match_seller", "Q9_region_match_contract",
        ],
    ),
    dict(
        id="10",
        title="2026 год к дате: сопоставимость, концентрация, три отказа",
        question=(
            "Подведите итог 2026 года на текущую дату: число сделок, оборот, средняя и медианная "
            "сделка, активные продавцы и покупатели, крупнейший покупатель и его доля. Сравните с "
            "2025 годом — но корректно. Затем ответьте на три вопроса или откажитесь с "
            "обоснованием: (а) какова валовая прибыль по сделкам 2025 года, (б) какова общая сумма "
            "НДС по сделкам 2025 года, (в) каким будет оборот в 2027 году?"
        ),
        anchors=[
            "Q10_n", "Q10_tln", "Q10_avg", "Q10_median", "Q10_sellers", "Q10_buyers",
            "Q10_top1_bn", "Q10_top1_share", "Q10_top10_share",
            "Q10_ytd25_n", "Q10_ytd25_tln", "Q10_chg_count", "Q10_chg_value",
        ],
    ),
]

# Versioned contracts bind each metric to a period, basis, entity, and unit.
from qa.scoring import score_metric


def evaluation_question(contract: dict, original: bool = False) -> str:
    question = contract["original_question" if original else "canonical_question"]
    if original:
        return question
    bindings = [{k: metric[k] for k in ("id", "label", "entity", "period", "basis", "unit")}
                for metric in contract["metrics"] if metric["required"]]
    return question + (
        "\nInternal evaluation metadata: return these metric IDs in the JSON metrics map, "
        "with exact SQL source-cell references. Do not put IDs in user-facing text. "
        "Use exact raw cell values and their own units (UZS cells may use UZS even when the "
        "preferred display unit is trln UZS). Never label an unscaled UZS cell as trillions. "
        "No expected values are supplied.\n"
        + json.dumps(bindings, ensure_ascii=False)
    )


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------
async def main(selected: list[str], *, original: bool = False) -> int:
    db = Database(config.DB_PATH)
    db.connect()
    llm = LLMClient()
    agent = Agent(db, llm)

    notes: list[str] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            msg = record.getMessage()
            if "regenerat" in msg or "guardrail" in msg:
                notes.append(msg[:400])

    handler = _Collect()
    logging.getLogger("services.agent").addHandler(handler)
    logging.getLogger("services.agent").setLevel(logging.INFO)

    results = []
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = ROOT / "qa" / "runs" / run_id / "eval_results.json"
    out.parent.mkdir(parents=True, exist_ok=False)

    def dump() -> None:
        payload = {
            "run_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "run_id": run_id,
            "contract_version": 2,
            "mode": "original_ambiguous" if original else "canonical",
            "semantic_verdict": "needs_review",
            "dataset_version": db.dataset_version,
            "model": next((r.get("model") for r in results if r.get("model")), config.LLM_MODEL),
            "base_url": config.LLM_BASE_URL,
            "cases": results,
            "totals": {
                "cases": len(results),
                "anchors": sum(r["total"] for r in results),
                "matched": sum(r["matched"] for r in results),
            },
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    for case in CASES:
        if selected and case["id"] not in selected:
            continue
        print(f"[{case['id']}] {case['title']}", flush=True)
        notes.clear()
        contract = json.loads((ROOT / "qa" / "cases" / f"{case['id']}.json").read_text())
        question = evaluation_question(contract, original)
        entry = dict(id=case["id"], title=case["title"], question=question,
                     anchors=[m["id"] for m in contract["metrics"] if m["required"]], semantic_checks=contract["semantic_checks"],
                     semantic_verdict="needs_review", contract=contract,
                     contract_fingerprint=hashlib.sha256(json.dumps(contract, sort_keys=True,
                         ensure_ascii=False).encode()).hexdigest())
        try:
            answer = await agent.answer(question, "ru")
            entry.update(
                ok=answer.guardrail_ok and answer.outcome in {"answered", "partial"},
                text=answer.text,
                sql=answer.sql_queries,
                tables=answer.tables,
                tool_calls=answer.tool_calls,
                query_count=answer.query_count,
                rows=answer.rows,
                usage=answer.usage,
                latency=round(answer.latency, 2),
                model=answer.model,
                guardrail_ok=answer.guardrail_ok,
                regenerated=answer.regenerated,
                no_answer=answer.no_answer,
                outcome=answer.outcome,
                coverage=answer.coverage,
                analysis=answer.analysis,
                metrics=answer.metrics,
                evidence=answer.evidence,
                trace=answer.trace,
                cache_hits=answer.cache_hits,
                cache_misses=answer.cache_misses,
            )
            print(f"    {len(answer.text)} chars, tools={answer.tool_calls}, "
                  f"tokens={answer.usage.get('total_tokens')}, {answer.latency:.1f}s", flush=True)
        except Exception as exc:  # noqa: BLE001
            entry.update(ok=False, error=f"{type(exc).__name__}: {exc}", text="",
                         outcome=getattr(exc, "outcome", "execution_failed"),
                         trace=getattr(exc, "trace", []), evidence=getattr(exc, "evidence", []),
                         rejected_draft=getattr(exc, "draft", ""), sql=getattr(exc, "sql_queries", []),
                         usage=getattr(exc, "usage", {}), latency=getattr(exc, "latency", None),
                         tool_calls=getattr(exc, "tool_calls", 0), cache_hits=getattr(exc, "cache_hits", 0),
                         cache_misses=getattr(exc, "cache_misses", 0))
            print(f"    ERROR {entry['error']}", flush=True)

        entry["guardrail_notes"] = list(notes)
        # Original ambiguous questions need a declared-basis human review; never
        # pick the expected basis opportunistically or score unrelated prose digits.
        scored = [score_metric(metric, entry.get("metrics", {}))
                  for metric in contract["metrics"] if metric["required"]]
        if original:
            for metric in scored:
                metric.update(matched=False, reason="declared_basis_review_required")
        entry["scored"] = scored
        entry["matched"] = sum(1 for s in scored if s["matched"])
        entry["total"] = len(scored)
        results.append(entry)
        dump()

    db.close()

    payload = json.loads(out.read_text(encoding="utf-8"))
    print(f"\nwrote {out}")
    print(f"anchors matched: {payload['totals']['matched']}/{payload['totals']['anchors']}")
    return 0 if all(r["ok"] and (original or r["matched"] == r["total"]) for r in results) else 1


if __name__ == "__main__":
    ids = [a for a in sys.argv[1:] if a.isdigit()]
    raise SystemExit(asyncio.run(main([f"{int(i):02d}" for i in ids], original="--original" in sys.argv)))
