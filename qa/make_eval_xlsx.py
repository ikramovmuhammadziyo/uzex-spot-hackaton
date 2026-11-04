"""Build the graded evaluation workbook from qa/eval_results.json.

    python qa/make_eval_xlsx.py [qa/eval_report.xlsx]

Three verdicts per case:
  verdict_vs_key  automatic: share of the case's gross-basis anchors found in the answer
                  PASS >= 90 %, PARTIAL >= 60 %, FAIL below  (QA_10_HARD_TESTS.md §1.4)
  data_accuracy   manual: every number the model stated reproduced exactly by an independent
                  recomputation under the model's own stated filter (qa/_alt_basis.py)
  overall         manual judgement combining both, plus whether the filter was disclosed

The manual columns are filled from REVIEW, written after reading all ten answers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent

# case -> (data_accuracy, overall, note)
REVIEW = {
    "01": ("PASS", "PARTIAL",
           "Все числа воспроизведены до копейки, но на своей базе: исключены 97 аннулированных "
           "сделок (1 270 вместо 1 367), поэтому 203,9 млн $ / 2,534 трлн сум / 4,87 % / ошибка "
           "25,40 млрд вместо 27,39 млрд. Фильтр раскрыт в ответе. Арифметика верна."),
    "02": ("PASS", "PARTIAL",
           "Полная таблица по трём механизмам, все суммы и проценты совпали с независимым "
           "пересчётом на базе «Исполнен + Частично» (99 324 сделки, 42,724 трлн). Расхождение "
           "только в счёте «ровно по старту»: 17 604 при точном равенстве против 18 029 при "
           "допуске 1 сум — вопрос не фиксирует допуск."),
    "03": ("PASS", "PASS",
           "Совпало 16 из 18 якорей: полная таблица восьми состояний, 188,316 трлн исполнено, "
           "14,738 трлн аннулировано, залог 1,538 трлн (10,44 % от аннулированной суммы), "
           "переходные состояния только в 2026. Пропущены общий залог 23,545 трлн и доля 6,53 % "
           "(модель дала другую, тоже верную метрику)."),
    "04": ("PASS", "PASS",
           "7 из 7 якорей. 22 648 сделок, 151 667 030 лотов, 172 439 661 единиц, 3,777 трлн сум, "
           "поставка 62,1 %, сельхозпродукция 1,938 трлн, крупнейшая сделка №373855 — всё точно. "
           "Отдельный плюс: сам предупредил, что суммировать единицы разных типов нельзя."),
    "05": ("N/A", "FAIL",
           "Пайплайн вернул пустой ответ (AgentError: the language model returned an empty "
           "answer) — вопрос про единицы измерения не отработан вообще. Это самый серьёзный "
           "провал прогона, потому что именно эта ловушка и проверялась."),
    "06": ("PASS", "PARTIAL",
           "Структура и все выводы верны (топ-5 по сумме, BK005 — лидер по количеству, 4 брокера "
           "никогда не продавцы, 113 из 120 активны). Значения — на базе без аннулированных: "
           "BK111 3 455,9 млрд / 3 829 сделок вместо 3 731,8 млрд / 4 128."),
    "07": ("PASS", "PASS",
           "18 из 22 якорей: 500 000 сделок, пропущено 4956 номеров, контракты 6616/6483/133 с "
           "разбивкой 127/6, участники 14 392/14 389/3, продавцы 392, покупатели 13 997, "
           "брокеры 120 и 4 без продаж, курс 1765 дней без пропусков, 822 понижения, "
           "сирот нет, 1236 торговых дней. Не назвал число 504 956, выходные и число 0 явно."),
    "08": ("N/A", "FAIL",
           "Ложный отказ. Модель посчитала верное значение 7 704 993 702 929,16 сум (совпадает "
           "с моим пересчётом) и 3,92 %, но guardrail счёл числа «неподтверждёнными» и заменил "
           "ответ на «В данных реестра ответа на этот вопрос нет» — при том что данные есть."),
    "09": ("PASS", "PARTIAL",
           "Семантика поля раскрыта верно и это главное: 99 324 из 99 324 совпадений с регионом "
           "продавца и 0 совпадений с регионом контракта. Суммы — на базе без аннулированных "
           "(Toshkent shahri 8 200,9 млрд вместо 8 832,2 млрд)."),
    "10": ("PASS", "PARTIAL",
           "Все числа точны на базе «Исполнен + Частично» (80 468 сделок, 41,083 трлн, средняя "
           "510 545 893, медиана 260 435 101, 335 продавцов, 12 328 покупателей, доля 2,34 %). "
           "Три отказа корректны. Но база «только завершённые» переворачивает знак динамики "
           "(−3,7 % по сделкам вместо +10,6 % по всем) и не оговорена как причина."

           ),
}


RETEST = [
    ("05", "run 1: FAIL", "AgentError: the language model returned an empty answer, 0 chars",
     "run 2: PASS", "968 chars, 5 tool rounds, wheat 2 187 806 t / cement 1 277 077 t / cotton "
     "1 267 043,77 t, explicitly refuses a single total and refuses to convert litres/pieces",
     "loop budget: the model spent all tool rounds probing and never emitted text; on retry it "
     "finished inside the budget"),
    ("08", "run 1: FAIL", "guardrail rejected 7 704 993 702 929,16 and 3,92 %, answer replaced "
     "by the no-answer sentence", "run 2: PASS",
     "1 010 chars, all 11 anchors present (459 563 paid, 0 late payments, 453 709 shipped, "
     "17 805 late = 3,92 %, avg 7.95 / max 15 days, 7,704,993,702,929.16 UZS), verify ok=True",
     "guardrail compares digit strings against SQL output; a value computed in prose (or rounded) "
     "never matches 7704993702929.156 exactly, so the retry succeeded only when the model "
     "re-queried the aggregate as a column"),
]

FINDINGS = [
    ("Точность данных", "PASS",
     "Во всех 8 ответах, которые вообще были получены, каждое число воспроизведено независимым "
     "пересчётом с точностью до копейки. Ни одной выдуманной или арифметически неверной цифры."),
    ("Системное расхождение", "WARNING",
     "Агент по умолчанию исключает «Аннулирован(Не оплачен)» (а в CASE 10 — и незавершённые "
     "состояния). Это документированная политика бота, но мои вопросы фильтр не фиксировали, "
     "поэтому 5 из 10 ответов численно расходятся с ключом, оставаясь внутренне верными."),
    ("Пустой ответ (нестабильно)", "UNSTABLE",
     "CASE 05 — пустой ответ в первом прогоне, корректный ответ во втором (см. Retest). "
     "Причина: бюджет 6 раундов инструментов исчерпан до того, как модель написала текст; "
     "фолбэка «ответь тем, что уже есть» нет."),
    ("Ложный отказ (нестабильно)", "UNSTABLE",
     "CASE 08 — guardrail отклонил верно посчитанные 7,705 трлн и 3,92 % и заменил ответ на "
     "«ответа нет»; повторный прогон дал полный корректный ответ. Худший тип ошибки: бот "
     "отрицает данные, которые сам только что получил."),
    ("Guardrail мешает производным числам", "WARNING",
     "В CASE 01, 02, 04, 06, 09 ответ уходил на регенерацию из-за «неподтверждённых» чисел "
     "(проценты, доли, производные суммы). Часть прошла, CASE 08 — нет. Причина: проверяются "
     "только числа, вернувшиеся из SQL, а арифметика в ответе запрещена промптом."),
    ("Флаг no_answer", "BUG",
     "CASE 10 содержит три корректных отказа на подвопросы (а)-(в), и is_no_answer() помечает "
     "весь ответ как отказ, потому что ищет фразу-маркер в любом месте текста."),
    ("Краткость", "INFO",
     "Ответы 0,8–2,2 тыс. знаков: системный промпт требует «краткий ответ, 2–5 строк». "
     "Многочастные вопросы покрываются не полностью — это формат, а не ошибка данных."),
]


def auto_verdict(case: dict) -> str:
    if not case.get("ok") or case.get("error") or case.get("no_answer"):
        return "FAIL"
    ratio = case["matched"] / case["total"] if case["total"] else 0
    if ratio >= 0.9:
        return "PASS"
    if ratio >= 0.6:
        return "PARTIAL"
    return "FAIL"


def paint(cell, value: str) -> None:
    color = {"PASS": "C6EFCE", "PARTIAL": "FFEB9C", "FAIL": "FFC7CE",
             "WARNING": "FFEB9C", "UNSTABLE": "FFEB9C", "BUG": "FFC7CE", "INFO": "DDEBF7"}.get(value)
    if color:
        cell.fill = PatternFill("solid", fgColor=color)
    cell.alignment = Alignment(horizontal="center", vertical="center")


def main(out_path: str) -> int:
    data = json.loads((ROOT / "qa" / "eval_results.json").read_text(encoding="utf-8"))
    cases = data["cases"]
    wb = Workbook()

    ws = wb.active
    ws.title = "Run"
    ws.append(["item", "value"])
    for c in ws[1]:
        c.fill, c.font = PatternFill("solid", fgColor="1F3864"), Font(bold=True, color="FFFFFF")
    for k, v in [
        ("model", data.get("model")),
        ("base_url", data.get("base_url")),
        ("run_at", data.get("run_at")),
        ("dataset", "500 000 сделок 03.01.2022–30.10.2026, снимок состояний на 30.10.2026"),
        ("pipeline", "services.agent -> services.tools (DuckDB) -> services.llm -> services.guardrails"),
        ("question language", "ru"),
        ("answer source", "живой вызов API на каждый кейс; без подсказок, без доступа к ключу ответов"),
        ("grading", "числовые якоря qa/anchors_data.py + независимый пересчёт qa/_alt_basis.py"),
        ("reference key", "qa/answer_key.xlsx (150 якорей, база «все состояния»)"),
    ]:
        ws.append([k, v])
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 115
    for r in ws.iter_rows(min_row=2):
        r[1].alignment = Alignment(wrap_text=True, vertical="top")

    ws = wb.create_sheet("Summary")
    ws.append(["case", "title", "verdict vs key", "data accuracy", "overall",
               "anchors", "of", "match %", "latency s", "tokens", "tools",
               "regenerated", "no-answer", "note"])
    for c in ws[1]:
        c.fill, c.font = PatternFill("solid", fgColor="1F3864"), Font(bold=True, color="FFFFFF")
    for case in cases:
        vs_key = auto_verdict(case)
        accuracy, overall, note = REVIEW.get(case["id"], ("", "", ""))
        pct = round(case["matched"] / case["total"] * 100, 1) if case["total"] else 0
        ws.append([
            case["id"], case["title"], vs_key, accuracy, overall,
            case["matched"], case["total"], pct, case.get("latency"),
            (case.get("usage") or {}).get("total_tokens"), case.get("tool_calls"),
            "да" if case.get("regenerated") else "нет",
            "да" if case.get("no_answer") else "нет", note,
        ])
    for i, w in enumerate([6, 42, 13, 13, 9, 8, 5, 9, 9, 9, 6, 12, 10, 95], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for idx in (2, 3, 4, 11, 12):
            paint(row[idx], row[idx].value)
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    ws = wb.create_sheet("Findings")
    ws.append(["finding", "severity", "evidence"])
    for c in ws[1]:
        c.fill, c.font = PatternFill("solid", fgColor="1F3864"), Font(bold=True, color="FFFFFF")
    for name, sev, text in FINDINGS:
        ws.append([name, sev, text])
    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 11
    ws.column_dimensions["C"].width = 110
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        paint(row[1], row[1].value)
        row[2].alignment = Alignment(wrap_text=True, vertical="top")

    ws = wb.create_sheet("Retest")
    ws.append(["case", "first run", "what happened", "second run", "what the second run produced",
               "root cause"])
    for c in ws[1]:
        c.fill, c.font = PatternFill("solid", fgColor="1F3864"), Font(bold=True, color="FFFFFF")
    for row in RETEST:
        ws.append(list(row))
    for i, w in enumerate([6, 13, 45, 13, 60, 60], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    ws = wb.create_sheet("Answers")
    ws.append(["case", "question (ru)", "answer (live model output)"])
    for c in ws[1]:
        c.fill, c.font = PatternFill("solid", fgColor="1F3864"), Font(bold=True, color="FFFFFF")
    for case in cases:
        ws.append([case["id"], case["question"], case.get("text") or case.get("error") or ""])
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 55
    ws.column_dimensions["C"].width = 125
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"

    ws = wb.create_sheet("Anchors")
    ws.append(["case", "anchor", "expected", "unit", "tolerance", "found in answer"])
    for c in ws[1]:
        c.fill, c.font = PatternFill("solid", fgColor="1F3864"), Font(bold=True, color="FFFFFF")
    for case in cases:
        for s in case["scored"]:
            ws.append([case["id"], s["anchor"], s["expected"], s["unit"], s["tol"],
                       "да" if s["matched"] else "нет"])
    for i, w in enumerate([6, 24, 22, 12, 12, 18], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        row[5].fill = PatternFill("solid", fgColor="C6EFCE" if row[5].value == "да" else "FFC7CE")

    ws = wb.create_sheet("SQL")
    ws.append(["case", "#", "query"])
    for c in ws[1]:
        c.fill, c.font = PatternFill("solid", fgColor="1F3864"), Font(bold=True, color="FFFFFF")
    for case in cases:
        for i, q in enumerate(case.get("sql") or [], start=1):
            ws.append([case["id"], i, q])
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 4
    ws.column_dimensions["C"].width = 150
    for row in ws.iter_rows(min_row=2):
        row[2].alignment = Alignment(wrap_text=True, vertical="top")

    wb.save(out_path)
    print(f"wrote {out_path}")
    counts = {"PASS": 0, "PARTIAL": 0, "FAIL": 0}
    for case in cases:
        _, overall, _ = REVIEW.get(case["id"], ("", auto_verdict(case), ""))
        counts[overall] = counts.get(overall, 0) + 1
        print(f"  {case['id']}  vs_key={auto_verdict(case):7s} accuracy={REVIEW.get(case['id'], ('?',))[0]:4s} "
              f"overall={overall:7s} {case['matched']:2d}/{case['total']:2d}")
    print("  overall:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "qa" / "eval_report.xlsx")))
