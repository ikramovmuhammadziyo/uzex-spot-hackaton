"""Recompute the anchors on the agent's own stated basis (annulled deals excluded,
or 'completed' = Исполнен + Исполнен(Частично)) to see whether its arithmetic is right."""

import glob
import pandas as pd

pd.set_option("display.width", 220)


def money(s):
    return pd.to_numeric(
        s.astype(str).str.replace("\u00a0", "", regex=False).str.replace(" ", "", regex=False),
        errors="coerce",
    )


c = pd.read_csv("contracts.csv", dtype=str).set_index("Номер контракта")
p = pd.read_csv("participants.csv", dtype=str)
d = pd.concat([pd.read_csv(f, dtype=str) for f in sorted(glob.glob("deals_20*.csv"))], ignore_index=True)
r = pd.read_csv("usd_rates.csv", dtype=str)

d["qty"] = money(d["Количество"]); d["sum"] = money(d["Сумма сделки"])
d["start"] = money(d["Стартовая цена"]); d["lot"] = money(d["Лот"])
d["del"] = money(d["Поставлено"])
d["date"] = pd.to_datetime(d["Дата сделки"], format="%d.%m.%Y"); d["year"] = d["date"].dt.year
d["vol"] = d["qty"] * d["lot"]; d["upx"] = d["sum"] / d["vol"]
d["cur"] = d["Номер контракта"].map(c["Валюта"]); d["usd"] = d["cur"] == "Доллар США"
r["k"] = money(r["Курс"]); r["dt"] = pd.to_datetime(r["Дата"], format="%d.%m.%Y")
d["rate"] = d["date"].map(dict(zip(r["dt"], r["k"])))
d["sum_uzs"] = d["sum"].where(~d["usd"], d["sum"] * d["rate"])
dead = "Аннулирован(Не оплачен)"
done = "Исполнен"
part = "Исполнен(Частично)"

print("=== CASE 01 basis: 2025 export, annulled excluded ===")
y = d[(d["year"] == 2025) & d["usd"]]
a = y[y["Состояние сделки"] != dead]
print("n", len(a), "usd", round(a["sum"].sum(), 2), "uzs", round(a["sum_uzs"].sum(), 2))
print("eff", round(a["sum_uzs"].sum() / a["sum"].sum(), 4))
tot25 = d[(d["year"] == 2025) & (d["Состояние сделки"] != dead)]["sum_uzs"].sum()
print("2025 turnover excl annulled", round(tot25, 2), "share", round(a["sum_uzs"].sum() / tot25 * 100, 4))
at = a["sum"].sum() * 12552.58
print("at 12552.58", round(at, 2), "delta", round(at - a["sum_uzs"].sum(), 2),
      "pct", round((at / a["sum_uzs"].sum() - 1) * 100, 4))

print("\n=== CASE 02 basis: 2024 completed (Исполнен + Частично) ===")
y = d[(d["year"] == 2024) & d["Состояние сделки"].isin([done, part])].copy()
y["dev"] = (y["upx"] / y["start"] - 1) * 100
y["diff"] = y["sum"] - y["start"] * y["vol"]
g = y.groupby("Тип торгов").agg(n=("dev", "size"), avg=("dev", "mean"), med=("dev", "median"),
                                mn=("dev", "min"), mx=("dev", "max"))
g["at_start"] = y.groupby("Тип торгов").apply(lambda x: (x["diff"].abs() < 1).sum(), include_groups=False)
g["prem_bn"] = y.groupby("Тип торгов").apply(
    lambda x: ((x["sum"] - x["start"] * x["vol"]) * x["rate"].where(x["usd"], 1)).sum() / 1e9,
    include_groups=False)
print(g.round(4).to_string())
print("total n", len(y), "turnover", round(y["sum_uzs"].sum(), 2), "net prem bn", round(g["prem_bn"].sum(), 2))

print("\n=== CASE 06 basis: 2025 seller-side, annulled excluded ===")
y = d[(d["year"] == 2025) & (d["Состояние сделки"] != dead)]
s1 = y.groupby("Брокер продавца").agg(n=("sum", "size"), uzs=("sum_uzs", "sum")).sort_values("uzs", ascending=False)
print("total", round(s1["uzs"].sum(), 2), "active", len(s1))
print((s1.head(5) / 1).round(2).to_string())
print(s1.tail(5).round(2).to_string())
print("by count top3", y.groupby("Брокер продавца").size().nlargest(3).to_dict())

print("\n=== CASE 09 basis: 2024 by region, annulled excluded ===")
y = d[(d["year"] == 2024) & (d["Состояние сделки"] != dead)]
rg = y.groupby("Регион")["sum_uzs"].sum().sort_values(ascending=False)
print(rg.head(5).round(2).to_string())
print("buyers/sellers region match", (y["Регион"] == y["ИНН продавца"].map(dict(zip(p["ИНН"], p["Регион"])))).mean())

print("\n=== CASE 10 basis: completed only, 2026 vs 2025 same window ===")
for yr, hi in ((2026, "2026-10-30"), (2025, "2025-10-30")):
    y = d[(d["year"] == yr) & (d["date"] <= pd.Timestamp(hi)) & d["Состояние сделки"].isin([done, part])]
    bs = y.groupby("ИНН покупателя")["sum_uzs"].sum().sort_values(ascending=False)
    print(yr, "n", len(y), "turnover", round(y["sum_uzs"].sum(), 2), "avg", round(y["sum_uzs"].mean(), 2),
          "median", round(y["sum_uzs"].median(), 2), "sellers", y["ИНН продавца"].nunique(),
          "buyers", y["ИНН покупателя"].nunique(),
          "top1 share", round(bs.iloc[0] / bs.sum() * 100, 4), "top1", round(bs.iloc[0], 2))

print("\n=== CASE 08 basis: late deliveries ===")
d["pay"] = pd.to_datetime(d["Дата оплаты"], format="%d.%m.%Y")
d["ship"] = pd.to_datetime(d["Дата поставки"], format="%d.%m.%Y")
d["term_ship"] = d["Номер контракта"].map(pd.to_numeric(c["Срок поставки"]))
sh = d[d["ship"].notna()].copy()
sh["sd"] = (sh["ship"] - sh["pay"]).dt.days
late = sh[sh["sd"] > sh["term_ship"]]
print("late n", len(late), "share", round(len(late) / len(sh) * 100, 4), "value", round(late["sum_uzs"].sum(), 2))
print("all states vs completed: same rows" if len(late) else "")

print("\n=== CASE 05 basis: 2026 mass ===")
y = d[d["year"] == 2026].copy()
y["t"] = None
y.loc[y["Единица измерения"] == "тонна", "t"] = y.loc[y["Единица измерения"] == "тонна", "vol"]
y.loc[y["Единица измерения"] == "килограмм", "t"] = y.loc[y["Единица измерения"] == "килограмм", "vol"] / 1000
tt = y.dropna(subset=["t"]).groupby("Номер контракта").size()
m = y.dropna(subset=["t"]).groupby(y["Номер контракта"].map(c["Код ТН ВЭД"]))["t"].sum().nlargest(4)
print(m.round(1).to_string())
