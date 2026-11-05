"""Internal synthesis envelope; user-facing output remains plain text."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from decimal import InvalidOperation
from typing import Any

from .analysis_spec import AnalysisSpec
from .numeric import MONEY_UNIT_SCALES, decimal_value, money_scale_from_column, rounded_equal


@dataclass
class Draft:
    text: str
    coverage: list[dict[str, str]] = field(default_factory=list)
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    analysis: AnalysisSpec | None = None
    outcome: str | None = None


def parse_draft(raw: str) -> Draft:
    value = raw.strip()
    prose = ""
    # Some providers append the envelope after prose despite JSON-only instructions.
    # Parse it explicitly so internal metrics never leak into user-facing text.
    trailing = re.search(r"```(?:json)?\s*\n?(\{.*?\})\s*```", value, re.S)
    if trailing:
        prose = "\n\n".join(part for part in (value[:trailing.start()].strip(),
                                                  value[trailing.end():].strip()) if part)
        value = trailing.group(1).strip()
    if value.startswith('```'):
        value = value.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    if not value.startswith('{'):
        marker = re.search(r'\{\s*"text"\s*:', value)
        if marker:
            prose = value[:marker.start()].strip()
            value = value[marker.start():]
        elif '"metrics"' in value or '```json' in value:
            raise ValueError('malformed internal envelope')
        else:
            return Draft(raw.strip())  # compatibility with plain-text clients
    try:
        payload = json.loads(value)
    except (ValueError, TypeError) as exc:
        raise ValueError('invalid synthesis JSON') from exc
    if not isinstance(payload, dict) or not isinstance(payload.get('text'), str):
        raise ValueError('synthesis must contain text')
    coverage = payload.get('coverage', [])
    metrics = payload.get('metrics', {})
    if not isinstance(coverage, list) or not isinstance(metrics, dict):
        raise ValueError('invalid coverage or metrics')
    for item in coverage:
        if (not isinstance(item, dict) or not isinstance(item.get('request'), str)
                or item.get('status') not in {'answered', 'unavailable', 'unresolved'}):
            raise ValueError('invalid coverage entry')
    analysis = AnalysisSpec.from_dict(payload['analysis']) if 'analysis' in payload else None
    if analysis:
        declared = {item['request'] for item in coverage}
        coverage.extend({'request': request, 'status': 'unresolved',
                         'reason': 'Requested output has no coverage entry'}
                        for request in analysis.requested_outputs if request not in declared)
    outcome = payload.get('outcome')
    if outcome is not None and outcome not in {'answered', 'partial', 'no_data', 'unsupported_request'}:
        raise ValueError('invalid answer outcome')
    text = payload['text'].strip()
    if prose:
        if not text or text.lower().rstrip('.') in {'see above', 'см. выше', 'см выше', 'above'}:
            text = prose
        # A substantive text field is authoritative; other prose is not displayed.
    elif text.lower().rstrip('.') in {'see above', 'см. выше', 'см выше', 'above'}:
        raise ValueError('envelope refers to missing prose')
    return Draft(text, coverage, metrics, analysis, outcome)


def verify_metrics(metrics: dict, results: list[dict]) -> bool:
    """Claims must reference an exact successful result cell, not arbitrary evidence."""
    by_id = {p.get('evidence_id'): p for p in results}
    for metric in metrics.values():
        try:
            source = metric['source']
            payload = by_id[source['evidence_id']]
            row = payload['rows'][source['row']]
            if type(source['row']) is not int or source['row'] < 0:
                return False
            entity = metric.get('entity', '')
            entity_columns = []
            if isinstance(entity, str) and re.fullmatch(r'BK\d{3}', entity):
                entity_columns = ['seller_broker', 'broker_code', 'code']
            elif isinstance(entity, str) and re.fullmatch(r'\d{9}', entity):
                entity_columns = ['inn', 'seller_inn', 'buyer_inn']
            elif isinstance(entity, str) and re.fullmatch(r'(?:\d{6}|\d{10})', entity):
                entity_columns = ['tnved_code', 'tnved']
            elif isinstance(entity, str) and re.search(r'viloyati|shahri', entity):
                entity_columns = ['region']
            elif isinstance(entity, str) and 'аукцион' in entity.lower():
                entity_columns = ['auction_type']
            elif isinstance(entity, str) and re.search(r'[А-Яа-я]', entity):
                entity_columns = ['product_category']
            explicit_entity_column = source.get('entity_column')
            if explicit_entity_column is not None:
                if row.get(explicit_entity_column) != entity:
                    return False
            available_entities = [str(row[column]) for column in entity_columns if column in row]
            if available_entities and entity not in available_entities:
                return False
            scope = payload.get('scope', {})
            if (scope.get('basis') in {'all', 'noncancelled', 'completed'}
                    and metric.get('basis') != scope['basis']
                    and not (metric.get('basis') == 'custom' and scope.get('states'))):
                return False
            value = row[source['column']]
            actual, claimed = decimal_value(str(value)), decimal_value(str(metric['value']))
            # Explicit SQL aliases establish monetary units. Unit conversion is
            # deterministic presentation; it must not change the analytical claim.
            source_scale = money_scale_from_column(source['column'])
            unit = metric.get('unit')
            if source_scale is not None and unit in MONEY_UNIT_SCALES:
                source_unit = next(u for u, scale in MONEY_UNIT_SCALES.items() if scale == source_scale)
                converted = actual * MONEY_UNIT_SCALES[source_unit] / MONEY_UNIT_SCALES[unit]
                binary_serialization = (isinstance(metric['value'], float) and
                                        abs(converted - claimed) <= decimal_value(str(math.ulp(metric['value']))))
                if not rounded_equal(converted, claimed) and not binary_serialization:
                    return False
                if source_unit != unit or actual != claimed:
                    metric['display_value'], metric['display_unit'] = metric['value'], unit
                    metric['value'], metric['unit'] = str(value), source_unit
            elif actual != claimed:
                return False
            if not all(isinstance(metric.get(k), str) and metric[k].strip()
                       for k in ('unit', 'basis', 'entity', 'period')):
                return False
        except (KeyError, TypeError, IndexError, InvalidOperation):
            return False
    return True


SYNTHESIS_CONTRACT = '''
Internal response contract (never show this envelope to the user): return JSON only:
{"text":"complete user-facing answer", "coverage":[{"request":"one requested output",
"status":"answered|unavailable|unresolved", "reason":"explanation if not answered"}],
"metrics":{}, "outcome":"answered|partial|no_data|unsupported_request",
"analysis":{"requested_period":"user period", "effective_period":"available window",
"state_basis":"all|noncancelled|completed|custom", "grouping":["column names"],
"measure":"contracted/delivered/remaining/value/count/mixed",
"requested_outputs":["same request labels as coverage"]}}
Resolve this analytical scope before choosing SQL; include it in the final envelope.
Scope is declared context, not evidence. Snapshot date is supplied by the application.
Track every subquestion in coverage; use one entry per requested output. This is your
coverage declaration, not proof. Answer supported parts even if another part is unavailable.
If the question explicitly requests metric IDs for evaluation, fill metrics by ID:
{"value":"exact raw SQL cell", "unit":"cell unit", "basis":"all|noncancelled|completed|custom",
"entity":"specified entity", "period":"specified period",
"source":{"evidence_id":"e1","row":0,"column":"returned column"}}.
Metric values must equal their referenced cells; compute unit conversions in SQL.
Keep metric IDs and source references out of text. Otherwise metrics may be empty.
'''
