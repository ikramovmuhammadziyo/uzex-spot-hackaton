"""Metric-bound evaluation. Prose alone is never proof of an anchor match."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from services.numeric import MONEY_UNIT_SCALES, decimal_value

UNIT_SCALES = {**{unit: ('UZS', scale) for unit, scale in MONEY_UNIT_SCALES.items()},
               'tonnes': ('mass', Decimal(1)), 'kg': ('mass', Decimal('.001'))}


def score_metric(spec: dict, claims: dict[str, Any]) -> dict:
    key = spec['id']
    result = {'anchor': key, 'expected': spec['expected'], 'unit': spec['unit'],
              'tol': spec['tolerance'], 'required': spec['required'], 'matched': False}
    claim = claims.get(key)
    if not isinstance(claim, dict):
        return {**result, 'reason': 'missing_bound_metric'}
    for field in ('basis', 'entity', 'period'):
        if claim.get(field) != spec[field]:
            return {**result, 'reason': f'{field}_mismatch'}
    try:
        source_dimension, source_scale = UNIT_SCALES.get(claim['unit'], (claim['unit'], Decimal(1)))
        target_dimension, target_scale = UNIT_SCALES.get(spec['unit'], (spec['unit'], Decimal(1)))
        if source_dimension != target_dimension:
            return {**result, 'reason': 'unit_mismatch'}
        actual = decimal_value(str(claim['value'])) * source_scale / target_scale
        expected = Decimal(str(spec['expected']))
        tolerance = Decimal(str(spec['tolerance']))
        matched = abs(actual - expected) <= tolerance
        return {**result, 'matched': matched, 'actual': str(actual),
                'reason': 'matched' if matched else 'value_mismatch'}
    except (KeyError, InvalidOperation, TypeError):
        return {**result, 'reason': 'invalid_metric'}
