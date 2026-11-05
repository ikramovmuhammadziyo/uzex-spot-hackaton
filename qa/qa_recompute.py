#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa/qa_recompute.py — canonical recomputation + self-check for QA_10_HARD_TESTS.md

Every number quoted in the test pack is recomputed here straight from the five
source CSVs and compared with the expected value stored in EXPECTED.

Usage:
    python qa/qa_recompute.py                 # recompute, verify, print table
    python qa/qa_recompute.py --xlsx out.xlsx # also write the answer-key workbook

Exit code 0 = every anchor reproduced inside its tolerance.
Exit code 1 = at least one anchor drifted (the file set or the logic changed).

Canonical rules implemented (see README.md / DB_README.md):
  * volume      = Количество * Лот                       (units of measure)
  * unit_price  = Сумма сделки / volume                  (contract currency)
  * UZS amount  = Сумма сделки                          if contract currency = UZS
                = Сумма сделки * usd_rates[deal date]   if contract currency = USD
    (the UZS branch must NOT be multiplied by the rate)
  * money fields carry spaces as thousand separators -> strip before parsing
"""

from __future__ import annotations

import argparse
import glob
import numbers
import os
import sys
from dataclasses import dataclass

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

TLN = 1e12
BN = 1e9

# ----------------------------------------------------------------------------
# expected anchors: key -> (expected value, unit, abs tolerance)
# ----------------------------------------------------------------------------
sys.path.insert(0, ROOT)
from qa.anchors_data import EXPECTED  # noqa: E402  (single source of truth)


def money(s: pd.Series) -> pd.Series:
    """Parse '1 234 567.8' -> float. Tolerates NBSP/regular spaces."""
    return pd.to_numeric(
        s.astype(str).str.replace("\u00a0", "", regex=False).str.replace(" ", "", regex=False),
        errors="coerce",
    )


def load():
    contracts = pd.read_csv("contracts.csv", dtype=str)
    participants = pd.read_csv("participants.csv", dtype=str)
    brokers = pd.read_csv("brokers.csv", dtype=str)
    rates = pd.read_csv("usd_rates.csv", dtype=str)
    deals = pd.concat(
        [pd.read_csv(f, dtype=str) for f in sorted(glob.glob("deals_20*.csv"))],
        ignore_index=True,
    )

    c = contracts.set_index("Номер контракта")
    deals["qty"] = money(deals["Количество"])
    deals["sum"] = money(deals["Сумма сделки"])
    deals["start"] = money(deals["Стартовая цена"])
    deals["lot"] = money(deals["Лот"])
    deals["delivered"] = money(deals["Поставлено"])
    deals["date"] = pd.to_datetime(deals["Дата сделки"], format="%d.%m.%Y")
    deals["year"] = deals["date"].dt.year
    deals["pay"] = pd.to_datetime(deals["Дата оплаты"], format="%d.%m.%Y")
    deals["ship"] = pd.to_datetime(deals["Дата поставки"], format="%d.%m.%Y")
    deals["volume"] = deals["qty"] * deals["lot"]
    deals["unit_price"] = deals["sum"] / deals["volume"]
    deals["currency"] = deals["Номер контракта"].map(c["Валюта"])
    deals["is_usd"] = deals["currency"] == "Доллар США"
    deals["category"] = deals["Номер контракта"].map(c["Категория товара"])
    deals["group"] = deals["Номер контракта"].map(c["Группа товара"])
    deals["tnved"] = deals["Номер контракта"].map(c["Код ТН ВЭД"])
    deals["unit"] = deals["Единица измерения"]
    deals["deposit_pct"] = deals["Номер контракта"].map(
        pd.to_numeric(c["Сумма залога"].str.replace(" %", "", regex=False))
    )
    deals["term_pay"] = deals["Номер контракта"].map(pd.to_numeric(c["Срок оплаты"]))
    deals["term_ship"] = deals["Номер контракта"].map(pd.to_numeric(c["Срок поставки"]))

    r = rates.copy()
    r["rate"] = money(r["Курс"])
    r["date"] = pd.to_datetime(r["Дата"], format="%d.%m.%Y")
    r = r.sort_values("date")
    deals["rate"] = deals["date"].map(dict(zip(r["date"], r["rate"])))

    # THE canonical conversion. UZS amounts are already in UZS.
    deals["sum_uzs"] = deals["sum"].where(~deals["is_usd"], deals["sum"] * deals["rate"])
    deals["prem_uzs"] = (deals["sum"] - deals["start"] * deals["volume"]) * (
        deals["rate"].where(deals["is_usd"], 1.0)
    )
    return deals, contracts, participants, brokers, r


def compute():
    d, c, p, b, r = load()
    a: dict[str, float] = {}
    add = a.__setitem__

    # global
    add("G_deals", len(d))
    nos = money(d["Номер сделки"])
    add("G_deal_no_min", nos.min())
    add("G_deal_no_max", nos.max())
    add("G_contracts", len(c))
    add("G_contracts_used", d["Номер контракта"].nunique())
    add("G_contracts_unused", len(c) - d["Номер контракта"].nunique())
    add("G_participants", len(p))
    add("G_sellers", d["ИНН продавца"].nunique())
    add("G_buyers", d["ИНН покупателя"].nunique())
    add("G_brokers", len(b))
    add("G_rates", len(r))
    add("G_turnover_tln", d["sum_uzs"].sum() / TLN)
    add("G_usd_deals", int(d["is_usd"].sum()))
    add("G_usd_sum", d.loc[d["is_usd"], "sum"].sum())
    add("G_usd_uzs_tln", d.loc[d["is_usd"], "sum_uzs"].sum() / TLN)

    # yearly
    for y in (2022, 2023, 2024, 2025, 2026):
        sub = d[d["year"] == y]
        add(f"Y{y}_n", len(sub))
        add(f"Y{y}_tln", sub["sum_uzs"].sum() / TLN)

    # Q1
    y = d[(d["year"] == 2025) & d["is_usd"]]
    usd, uzs, n = y["sum"].sum(), y["sum_uzs"].sum(), len(y)
    add("Q1_2025_export_n", n)
    add("Q1_2025_export_usd", usd)
    add("Q1_2025_export_uzs", uzs)
    add("Q1_eff_rate", uzs / usd)
    add("Q1_share_value_pct", uzs / d[d["year"] == 2025]["sum_uzs"].sum() * 100)
    add("Q1_share_count_pct", n / len(d[d["year"] == 2025]) * 100)
    at_ye = usd * 12552.58
    add("Q1_at_ye_rate", at_ye)
    add("Q1_error_vs_ye", at_ye - uzs)
    add("Q1_error_pct", (at_ye / uzs - 1) * 100)

    # Q2
    y = d[d["year"] == 2024].copy()
    y["dev"] = (y["unit_price"] / y["start"] - 1) * 100
    y["diff"] = y["sum"] - y["start"] * y["volume"]
    for code, name in (
        ("eng", "Английский аукцион"),
        ("dbl", "Двусторонний аукцион"),
        ("rev", "Обратный аукцион"),
    ):
        s = y[y["Тип торгов"] == name]
        add(f"Q2_{code}_n", len(s))
        add(f"Q2_{code}_avg", s["dev"].mean())
        add(f"Q2_{code}_med", s["dev"].median())
        add(f"Q2_{code}_at_start", int((s["diff"].abs() < 1).sum()))
        add(f"Q2_{code}_prem_bn", s["prem_uzs"].sum() / BN)
    add("Q2_eng_max", y.loc[y["Тип торгов"] == "Английский аукцион", "dev"].max())
    add("Q2_rev_min", y.loc[y["Тип торгов"] == "Обратный аукцион", "dev"].min())
    add("Q2_net_prem_bn", y["prem_uzs"].sum() / BN)
    add("Q2_net_pct", y["prem_uzs"].sum() / y["sum_uzs"].sum() * 100)

    # Q3
    tot = d["sum_uzs"].sum()
    st = d.groupby("Состояние сделки").agg(n=("sum", "size"), uzs=("sum_uzs", "sum"))
    for key, label in (
        ("done", "Исполнен"),
        ("ann", "Аннулирован(Не оплачен)"),
        ("part", "Исполнен(Частично)"),
        ("paid", "Оплачен"),
        ("signed", "Заключен"),
        ("wait", "Ждёт оплату"),
        ("new", "Новый"),
        ("unsigned", "Не подписан"),
    ):
        add(f"Q3_{key}_n", int(st.loc[label, "n"]))
        add(f"Q3_{key}_pct_n", st.loc[label, "n"] / len(d) * 100)
        add(f"Q3_{key}_tln", st.loc[label, "uzs"] / TLN)
        add(f"Q3_{key}_pct_v", st.loc[label, "uzs"] / tot * 100)
    dep = (d["sum_uzs"] * d["deposit_pct"] / 100).sum()
    ann = d[d["Состояние сделки"] == "Аннулирован(Не оплачен)"]
    dep_ann = (ann["sum_uzs"] * ann["deposit_pct"] / 100).sum()
    add("Q3_deposit_all_tln", dep / TLN)
    add("Q3_deposit_ann_tln", dep_ann / TLN)
    add("Q3_deposit_ann_share", dep_ann / dep * 100)

    # Q4
    par = d[d["Состояние сделки"] == "Исполнен(Частично)"].copy()
    par["und_lots"] = par["qty"] - par["delivered"]
    par["und_vol"] = par["und_lots"] * par["lot"]
    par["und_uzs"] = par["und_vol"] * par["unit_price"] * par["rate"].where(par["is_usd"], 1.0)
    add("Q4_deals", len(par))
    add("Q4_und_lots", par["und_lots"].sum())
    add("Q4_und_vol", par["und_vol"].sum())
    add("Q4_tln", par["und_uzs"].sum() / TLN)
    add("Q4_fill_pct", par["delivered"].sum() / par["qty"].sum() * 100)
    add("Q4_avg_fill_pct", (par["delivered"] / par["qty"]).mean() * 100)
    add("Q4_agri_tln", par[par["category"] == "Сельскохозяйственная продукция"]["und_uzs"].sum() / TLN)
    add("Q4_max_und_lots", par["und_lots"].max())

    # Q5
    y = d[d["year"] == 2026].copy()

    def to_tonnes(row):
        if row["unit"] == "тонна":
            return row["volume"]
        if row["unit"] == "килограмм":
            return row["volume"] / 1000.0
        return None

    y["t"] = y.apply(to_tonnes, axis=1)
    tt = y.dropna(subset=["t"]).groupby("tnved")["t"].sum()
    add("Q5_wheat_t", tt.get("100199", 0))
    add("Q5_cement_t", tt.get("252329", 0))
    add("Q5_cotton_t", tt.get("520100", 0))
    add("Q5_cotton_kg", y.loc[y["tnved"] == "520100", "volume"].sum())
    add("Q5_naive_cotton", y.groupby("tnved")["volume"].sum().get("520100", 0))
    add("Q5_units_2026", y["unit"].nunique())

    # Q6
    names = dict(zip(b["Код брокера"], b["Наименование"]))
    y = d[d["year"] == 2025]
    s1 = y.groupby("Брокер продавца").agg(n=("sum", "size"), uzs=("sum_uzs", "sum"))
    tot25 = s1["uzs"].sum()
    for code in ("BK111", "BK106", "BK102", "BK047", "BK005", "BK031"):
        add(f"Q6_{code.lower()}_n", int(s1.loc[code, "n"]))
        add(f"Q6_{code.lower()}_bn", s1.loc[code, "uzs"] / BN)
    add("Q6_bk111_share", s1.loc["BK111", "uzs"] / tot25 * 100)
    never = sorted(set(b["Код брокера"]) - set(d["Брокер продавца"]))
    add("Q6_never_seller", len(never))
    add("Q6_active_2025", s1.shape[0])

    # Q7
    span = nos.max() - nos.min() + 1
    add("Q7_span", span)
    add("Q7_gaps", span - len(nos))
    add("Q7_dup", nos.duplicated().sum())
    unused = set(c["Номер контракта"]) - set(d["Номер контракта"])
    add("Q7_unused_uzs", sum(1 for x in unused if c.set_index("Номер контракта").loc[x, "Валюта"] == "Узбекский сум"))
    add("Q7_unused_usd", sum(1 for x in unused if c.set_index("Номер контракта").loc[x, "Валюта"] == "Доллар США"))
    used_ppl = set(d["ИНН продавца"]) | set(d["ИНН покупателя"])
    add("Q7_p_unused", len(set(p["ИНН"]) - used_ppl))
    add("Q7_rate_days", (r["date"].max() - r["date"].min()).days + 1)
    add("Q7_rate_missing", (r["date"].max() - r["date"].min()).days + 1 - len(r))
    add("Q7_rate_min", r["rate"].min())
    add("Q7_rate_max", r["rate"].max())
    add("Q7_rate_down_days", int((r["rate"].diff() < 0).sum()))
    orphans = 0
    orphans += (~d["Номер контракта"].isin(set(c["Номер контракта"]))).sum()
    orphans += (~d["ИНН продавца"].isin(set(p["ИНН"]))).sum()
    orphans += (~d["ИНН покупателя"].isin(set(p["ИНН"]))).sum()
    orphans += (~d["Брокер продавца"].isin(set(b["Код брокера"]))).sum()
    orphans += (~d["Брокер покупателя"].isin(set(b["Код брокера"]))).sum()
    orphans += (~d["Дата сделки"].isin(set(r["Дата"]))).sum()
    add("Q7_orphans", orphans)
    add("Q7_deal_dates", d["Дата сделки"].nunique())
    add("Q7_weekend", int(d["date"].dt.dayofweek.isin([5, 6]).sum()))
    spot = d[d["Номер сделки"] == "185158"].iloc[0]
    add("Q7_spot_volume", spot["volume"])
    add("Q7_spot_sum", spot["sum"])
    add("Q7_spot_unit_price", spot["unit_price"])
    add("Q7_spot_delivered", spot["delivered"])

    # Q8
    paid = d[d["pay"].notna()].copy()
    paid["pay_days"] = (paid["pay"] - paid["date"]).dt.days
    add("Q8_paid", len(paid))
    add("Q8_late_pay", int((paid["pay_days"] > paid["term_pay"]).sum()))
    add("Q8_pay_max", paid["pay_days"].max())
    add("Q8_term_pay_max", d["term_pay"].max())
    sh = d[d["ship"].notna()].copy()
    sh["ship_days"] = (sh["ship"] - sh["pay"]).dt.days
    late = sh[sh["ship_days"] > sh["term_ship"]]
    add("Q8_shipped", len(sh))
    add("Q8_late_sup", len(late))
    add("Q8_late_pct", len(late) / len(sh) * 100)
    add("Q8_overrun_avg", (late["ship_days"] - late["term_ship"]).mean())
    add("Q8_overrun_max", (late["ship_days"] - late["term_ship"]).max())
    add("Q8_late_tln", late["sum_uzs"].sum() / TLN)
    add("Q8_late_share_shipped", late["sum_uzs"].sum() / sh["sum_uzs"].sum() * 100)
    add("Q8_late_agri", int((late["category"] == "Сельскохозяйственная продукция").sum()))
    add("Q8_on_time_exact", int((sh["ship_days"] == sh["term_ship"]).sum()))
    add("Q8_early", int((sh["ship_days"] < sh["term_ship"]).sum()))

    # Q9
    y = d[d["year"] == 2024]
    rg = y.groupby("Регион")["sum_uzs"].sum().sort_values(ascending=False)
    add("Q9_toshkent_bn", rg.iloc[0] / BN)
    add("Q9_toshkent_share", rg.iloc[0] / rg.sum() * 100)
    add("Q9_namangan_bn", rg.iloc[1] / BN)
    add("Q9_xorazm_bn", rg.iloc[2] / BN)
    add("Q9_sirdaryo_bn", rg.get("Sirdaryo viloyati", 0) / BN)
    add("Q9_toshkent_v_bn", rg.get("Toshkent viloyati", 0) / BN)
    reg = dict(zip(p["ИНН"], p["Регион"]))
    add("Q9_region_match_seller", (d["Регион"] == d["ИНН продавца"].map(reg)).mean() * 100)
    add("Q9_region_match_contract", (d["Регион"] == d["Номер контракта"].map(c.set_index("Номер контракта")["Регион"])).mean() * 100)

    # Q10
    y = d[d["year"] == 2026]
    y25 = d[(d["year"] == 2025) & (d["date"] <= pd.Timestamp("2025-10-30"))]
    add("Q10_n", len(y))
    add("Q10_tln", y["sum_uzs"].sum() / TLN)
    add("Q10_avg", y["sum_uzs"].mean())
    add("Q10_median", y["sum_uzs"].median())
    add("Q10_sellers", y["ИНН продавца"].nunique())
    add("Q10_buyers", y["ИНН покупателя"].nunique())
    add("Q10_ytd25_n", len(y25))
    add("Q10_ytd25_tln", y25["sum_uzs"].sum() / TLN)
    add("Q10_chg_count", (len(y) / len(y25) - 1) * 100)
    add("Q10_chg_value", (y["sum_uzs"].sum() / y25["sum_uzs"].sum() - 1) * 100)
    bs = y.groupby("ИНН покупателя")["sum_uzs"].sum().sort_values(ascending=False)
    add("Q10_top1_bn", bs.iloc[0] / BN)
    add("Q10_top1_share", bs.iloc[0] / bs.sum() * 100)
    add("Q10_top10_share", bs.head(10).sum() / bs.sum() * 100)

    return a, d, c, p, b, r


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default="", help="write answer key workbook to this path")
    args = ap.parse_args(argv)

    a, d, c, p, b, r = compute()

    rows, failed = [], 0
    for key, (exp, unit, tol) in EXPECTED.items():
        got = a.get(key)
        if got is None:
            rows.append((key, exp, None, unit, tol, "MISSING"))
            failed += 1
            continue
        ok = abs(got - exp) <= tol if tol else abs(got - exp) <= 1e-9
        if not ok:
            failed += 1
        rows.append((key, exp, got, unit, tol, "PASS" if ok else "FAIL"))

    print(f"{'key':28s} {'expected':>20s} {'computed':>20s} {'tol':>10s}  unit / status")
    for key, exp, got, unit, tol, status in rows:
        gs = f"{got:20.4f}" if isinstance(got, numbers.Real) else f"{'—':>20s}"
        print(f"{key:28s} {exp:20.4f} {gs} {tol:10.4g}  {unit:12s} {status}")

    print()
    print(f"anchors: {len(rows)}   passed: {len(rows)-failed}   failed: {failed}")
    print(f"dataset: deals={len(d)} contracts={len(c)} participants={len(p)} brokers={len(b)} rates={len(r)}")

    if args.xlsx:
        write_xlsx(args.xlsx, rows)

    return 0 if failed == 0 else 1


def write_xlsx(path, rows):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    head_fill = PatternFill("solid", fgColor="1F3864")
    head_font = Font(bold=True, color="FFFFFF")

    ws = wb.active
    ws.title = "Anchors"
    ws.append(["anchor", "case", "expected_in_key", "recomputed_from_csv", "tolerance", "unit", "check"])
    for cell in ws[1]:
        cell.fill, cell.font = head_fill, head_font
    for key, exp, got, unit, tol, status in rows:
        ws.append([key, key.split("_")[0], exp, got, tol, unit, "MATCH" if status == "PASS" else "DRIFT"])
    widths = [30, 8, 20, 20, 12, 14, 10]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"

    ws2 = wb.create_sheet("Legend")
    ws2.append(["term", "meaning"])
    for cell in ws2[1]:
        cell.fill, cell.font = head_fill, head_font
    for k, v in [
        ("check = MATCH", "the value recomputed from the CSVs equals expected_in_key within tolerance. "
                          "This is a data-consistency check of the answer key, NOT a score of any AI model."),
        ("expected_in_key", "the number frozen in qa/qa_recompute.py and quoted in QA_10_HARD_TESTS.md"),
        ("recomputed_from_csv", "the number this run produced from deals_*.csv / contracts.csv / participants.csv / brokers.csv / usd_rates.csv"),
        ("trln / bn", "10^12 / 10^9 UZS"),
        ("unit", "Единица измерения: units of measure of the contract"),
        ("lot", "Лот: units per lot; volume = Количество x Лот"),
        ("sum_uzs", "Сумма сделки for UZS contracts; Сумма сделки x rate(deal date) for USD contracts"),
        ("tolerance", "abs tolerance used by qa_recompute.py"),
        ("snapshot", "all deal states as of 30.10.2026"),
    ]:
        ws2.append([k, v])
    ws2.column_dimensions["A"].width = 20
    ws2.column_dimensions["B"].width = 95
    for row in ws2.iter_rows(min_row=2):
        row[1].alignment = Alignment(wrap_text=True, vertical="top")

    wb.save(path)
    print(f"wrote {path}")


if __name__ == "__main__":
    sys.exit(main())
