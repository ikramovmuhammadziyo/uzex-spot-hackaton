"""Declared analytical scope, kept separate from query-derived evidence."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from data import config


@dataclass(frozen=True)
class AnalysisSpec:
    requested_period: str = ''
    effective_period: str = ''
    state_basis: str = 'custom'
    grouping: list[str] = field(default_factory=list)
    measure: str = 'mixed'
    requested_outputs: list[str] = field(default_factory=list)
    snapshot_date: str = config.DEALS_MAX_DATE

    @classmethod
    def from_dict(cls, payload: dict) -> AnalysisSpec:
        if not isinstance(payload, dict):
            raise ValueError('analysis must be an object')
        basis = payload.get('state_basis', 'custom')
        if basis not in {'all', 'noncancelled', 'completed', 'custom'}:
            raise ValueError('unknown state basis')
        for key in ('grouping', 'requested_outputs'):
            if not isinstance(payload.get(key, []), list) or not all(
                    isinstance(item, str) and item.strip() for item in payload.get(key, [])):
                raise ValueError(f'invalid analysis {key}')
        for key in ('requested_period', 'effective_period', 'measure'):
            if not isinstance(payload.get(key, ''), str):
                raise ValueError(f'invalid analysis {key}')
        return cls(**{key: payload[key] for key in (
            'requested_period', 'effective_period', 'state_basis', 'grouping', 'measure',
            'requested_outputs') if key in payload})

    def to_dict(self) -> dict:
        return asdict(self)
