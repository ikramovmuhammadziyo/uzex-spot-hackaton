"""Business regression: commodity grouping across names/forms and unit conversion."""
from __future__ import annotations

import csv
from collections import defaultdict
from decimal import Decimal

import pytest

from data import config
from services.database import Database
from services.tools import ToolRunner
import json


async def test_commodity_mass_ranking_matches_independent_csv_reference():
    if not config.DB_PATH.is_file():
        pytest.skip('local dataset is unavailable')
    with (config.BASE_DIR / 'contracts.csv').open() as file:
        contracts = {r['Номер контракта']: r['Код ТН ВЭД'] for r in csv.DictReader(file)}
    expected = defaultdict(Decimal)
    with (config.BASE_DIR / 'deals_2026.csv').open() as file:
        for row in csv.DictReader(file):
            if row['Состояние сделки'] == 'Аннулирован(Не оплачен)':
                continue
            unit = row['Единица измерения']
            if unit not in ('килограмм', 'тонна'):
                continue
            volume = Decimal(row['Количество'].replace(' ', '')) * Decimal(row['Лот'].replace(' ', ''))
            expected[contracts[row['Номер контракта']]] += volume / (1000 if unit == 'килограмм' else 1)
    top = sorted(expected.items(), key=lambda x: x[1], reverse=True)[:3]
    db = Database(); db.connect()
    try:
        payload = json.loads(await ToolRunner(db).run('run_sql', {'query': """
          SELECT tnved_code, SUM(CASE WHEN unit='килограмм' THEN volume/1000.0 ELSE volume END) AS tonnes
          FROM deals_enriched
          WHERE deal_date >= DATE '2026-01-01' AND deal_date < DATE '2027-01-01'
            AND deal_state <> 'Аннулирован(Не оплачен)' AND unit IN ('тонна','килограмм')
          GROUP BY tnved_code ORDER BY tonnes DESC LIMIT 3
        """}))
    finally:
        db.close()
    assert payload['ok']
    assert [row['tnved_code'] for row in payload['rows']] == [code for code, _ in top]
    for row, (_, amount) in zip(payload['rows'], top):
        assert abs(Decimal(str(row['tonnes'])) - amount) < Decimal('.000001')
