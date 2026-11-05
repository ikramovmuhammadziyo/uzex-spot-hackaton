"""Independent CSV references for ambiguous state bases; never chooses the best score.

Run: .venv/bin/python -m qa.recompute_variants > /tmp/qa_variants.json
The original frozen gross-basis anchors remain unchanged.
"""
from __future__ import annotations

import json

from qa.qa_recompute import load


def compute_variants():
    original, contracts, participants, brokers, rates = load()
    variants = {}
    for basis in ('all', 'noncancelled', 'completed'):
        d = original
        if basis == 'noncancelled':
            d = d[d['Состояние сделки'] != 'Аннулирован(Не оплачен)']
        elif basis == 'completed':
            d = d[d['Состояние сделки'].isin(['Исполнен', 'Исполнен(Частично)'])]
        a = {}
        partial_mass = d[(d['Состояние сделки']=='Исполнен(Частично)') & d['unit'].isin(['тонна','килограмм'])]
        remaining = (partial_mass['qty']-partial_mass['delivered'])*partial_mass['lot']
        a['Q4_max_und_mass_t'] = remaining.where(partial_mass['unit']=='тонна', remaining/1000).max()
        y = d[d['year'] == 2025]
        exp = y[y['is_usd']]
        usd, uzs = exp['sum'].sum(), exp['sum_uzs'].sum()
        year_end = usd * 12552.58
        a.update(Q1_2025_export_n=len(exp), Q1_2025_export_usd=usd,
                 Q1_2025_export_uzs=uzs, Q1_share_value_pct=100*uzs/y['sum_uzs'].sum(),
                 Q1_eff_rate=uzs/usd, Q1_at_ye_rate=year_end,
                 Q1_error_vs_ye=year_end-uzs, Q1_error_pct=100*(year_end-uzs)/uzs)
        auctions = d[d['year'] == 2024]
        for code, name in [('eng', 'Английский аукцион'),
                           ('dbl', 'Двусторонний аукцион'), ('rev', 'Обратный аукцион')]:
            x = auctions[auctions['Тип торгов'] == name]
            deviation = (x['unit_price']/x['start']-1)*100
            for suffix, value in dict(n=len(x), avg=deviation.mean(), med=deviation.median(),
                                      min=deviation.min(), max=deviation.max(),
                                      at_start=((x['sum']-x['start']*x['volume']).abs()<1).sum(),
                                      prem_bn=x['prem_uzs'].sum()/1e9).items():
                a[f'Q2_{code}_{suffix}'] = value
        a['Q2_net_prem_bn'] = auctions['prem_uzs'].sum()/1e9
        a['Q2_net_pct'] = 100*auctions['prem_uzs'].sum()/auctions['sum_uzs'].sum()
        mass = d[(d['year'] == 2026) & d['unit'].isin(['тонна', 'килограмм'])].copy()
        mass['tonnes'] = mass['volume'].where(mass['unit'] == 'тонна', mass['volume']/1000)
        totals = mass.groupby('tnved')['tonnes'].sum()
        for name, code in [('wheat', '100199'), ('cement', '252329'), ('cotton', '520100')]:
            a[f'Q5_{name}_t'] = totals.get(code, 0)
        for code, group in y.groupby('Брокер продавца'):
            a[f'Q6_{code.lower()}_n'] = len(group)
            a[f'Q6_{code.lower()}_bn'] = group['sum_uzs'].sum()/1e9
        a['Q6_bk111_share'] = 100*a['Q6_bk111_bn']*1e9/y['sum_uzs'].sum()
        a['Q6_active_2025'] = y['Брокер продавца'].nunique()
        # 'Never' uses the full registry, not the selected year/status basis.
        a['Q6_never_seller'] = len(set(brokers['Код брокера'])-set(original['Брокер продавца']))
        regions = d[d['year'] == 2024].groupby('Регион')['sum_uzs'].sum()
        for key, label in [('toshkent', 'Toshkent shahri'), ('namangan', 'Namangan viloyati'),
                           ('xorazm', 'Xorazm viloyati'), ('sirdaryo', 'Sirdaryo viloyati'),
                           ('toshkent_v', 'Toshkent viloyati')]:
            a[f'Q9_{key}_bn'] = regions[label]/1e9
        a['Q9_toshkent_share'] = 100*regions['Toshkent shahri']/regions.sum()
        yy = d[d['year'] == 2026]
        previous = y[y['date'].dt.strftime('%m-%d') <= '10-30']
        buyers = yy.groupby('ИНН покупателя')['sum_uzs'].sum().sort_values(ascending=False)
        a.update(Q10_n=len(yy), Q10_tln=yy['sum_uzs'].sum()/1e12,
                 Q10_avg=yy['sum_uzs'].mean(), Q10_median=yy['sum_uzs'].median(),
                 Q10_sellers=yy['ИНН продавца'].nunique(), Q10_buyers=yy['ИНН покупателя'].nunique(),
                 Q10_ytd25_n=len(previous), Q10_ytd25_tln=previous['sum_uzs'].sum()/1e12,
                 Q10_chg_count=100*(len(yy)/len(previous)-1),
                 Q10_chg_value=100*(yy['sum_uzs'].sum()/previous['sum_uzs'].sum()-1),
                 Q10_top1_bn=buyers.iloc[0]/1e9, Q10_top1_share=100*buyers.iloc[0]/buyers.sum(),
                 Q10_top10_share=100*buyers.head(10).sum()/buyers.sum())
        variants[basis] = {key: float(value) for key, value in a.items()}
    return variants


if __name__ == '__main__':
    print(json.dumps(compute_variants(), ensure_ascii=False, indent=2))
