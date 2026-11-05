"""Strict decimal parsing shared by evidence verification and evaluation."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

MONEY_UNIT_SCALES = {"UZS": Decimal(1), "mln UZS": Decimal("1e6"), "bn UZS": Decimal("1e9"), "trln UZS": Decimal("1e12")}

SCALES = {'трлн': Decimal('1e12'), 'trln': Decimal('1e12'),
          'млрд': Decimal('1e9'), 'bn': Decimal('1e9'),
          'млн': Decimal('1e6'), 'mln': Decimal('1e6'),
          'тыс': Decimal('1e3')}


def decimal_value(raw: str) -> Decimal:
    value = re.sub(r'[\s\u00a0\u202f\u2009]', '', raw).replace('−', '-')
    if ',' in value and '.' in value:
        # The last separator is decimal; earlier groups must contain three digits.
        sep = ',' if value.rfind(',') > value.rfind('.') else '.'
        group = '.' if sep == ',' else ','
        integer, fraction = value.rsplit(sep, 1)
        if not re.fullmatch(r'[+-]?\d{1,3}(?:' + re.escape(group) + r'\d{3})+', integer):
            raise InvalidOperation('invalid grouping')
        value = integer.replace(group, '') + '.' + fraction
    elif value.count(',') > 1 or value.count('.') > 1:
        sep = ',' if ',' in value else '.'
        if not re.fullmatch(r'[+-]?\d{1,3}(?:' + re.escape(sep) + r'\d{3})+', value):
            raise InvalidOperation('invalid grouping')
        value = value.replace(sep, '')
    else:
        # A single punctuation separator is decimal; use spaces for thousands.
        value = value.replace(',', '.')
    result = Decimal(value)
    if not result.is_finite():
        raise InvalidOperation('nonfinite value')
    return result


def rounded_equal(source: Decimal, shown: Decimal, *, allow_integer: bool = False) -> bool:
    """Only decimal displays may round; integers/counts remain exact."""
    if source == shown:
        return True
    if shown.as_tuple().exponent >= 0 and not allow_integer:
        return False
    with localcontext() as ctx:
        ctx.prec = max(60, len(source.as_tuple().digits) + 10)
        return source.quantize(Decimal(1).scaleb(shown.as_tuple().exponent),
                               rounding=ROUND_HALF_UP) == shown


def money_scale_from_column(column: str) -> Decimal | None:
    """Recognize explicit unit tokens, including aliases with trailing scope labels."""
    name = column.lower()
    match = re.search(r'(?:^|_)(trln|tln|bn|mln)(?:_uzs)?(?:_|$)', name)
    if not match:
        match = re.search(r'(?:^|_)uzs_(trln|tln|bn|mln)(?:_|$)', name)
    if match:
        return {'trln': Decimal('1e12'), 'tln': Decimal('1e12'),
                'bn': Decimal('1e9'), 'mln': Decimal('1e6')}[match.group(1)]
    if re.search(r'(?:^|_)uzs(?:_|$)', name):
        return Decimal(1)
    return None
