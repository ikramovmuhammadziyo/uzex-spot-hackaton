from qa.scoring import score_metric
from services.answer_contract import verify_metrics


def spec():
    return dict(id='export_uzs', entity='export', period='2025', basis='noncancelled',
                expected=1000, unit='UZS', tolerance=0, required=True)


def claim(**kwargs):
    return dict(value='1000', unit='UZS', entity='export', period='2025',
                basis='noncancelled', **kwargs)


def test_metric_binding_rejects_unrelated_value():
    assert not score_metric(spec(), {'other': claim()})['matched']
    assert score_metric(spec(), {'export_uzs': claim()})['matched']


def test_basis_entity_period_units_and_signs_are_exact():
    for field, value in [('basis', 'all'), ('entity', 'domestic'), ('period', '2024'),
                         ('unit', 'USD'), ('value', '-1000'), ('value', '1001')]:
        metric = claim(); metric[field] = value
        assert not score_metric(spec(), {'export_uzs': metric})['matched']


def test_explicit_unit_scaling_only():
    metric = claim(); metric.update(unit='bn UZS', value='0.000001')
    assert score_metric(spec(), {'export_uzs': metric})['matched']


def test_cell_references_must_match_successful_evidence():
    metric = claim(source={'evidence_id': 'e2', 'row': 0, 'column': 'total'})
    evidence = [{'evidence_id': 'e2', 'rows': [{'total': '1000'}]}]
    assert verify_metrics({'export_uzs': metric}, evidence)
    metric['value'] = '1001'
    assert not verify_metrics({'export_uzs': metric}, evidence)
    metric['value'] = '1000'; metric['source']['row'] = -1
    assert not verify_metrics({'export_uzs': metric}, evidence)


def test_trailing_envelope_is_never_exposed_to_user():
    import json
    from services.answer_contract import parse_draft
    raw = '1000 сум.\n```json\n' + json.dumps({'text': 'see above', 'coverage': [], 'metrics': {}}) + '\n```'
    assert parse_draft(raw).text == '1000 сум.'


def test_unfenced_trailing_envelope_is_also_hidden():
    import json
    from services.answer_contract import parse_draft
    raw = '1000 сум.\n' + json.dumps({'text': 'see above', 'coverage': [], 'metrics': {}})
    assert parse_draft(raw).text == '1000 сум.'


def test_fenced_envelope_with_trailing_footer_is_hidden():
    import json
    from services.answer_contract import parse_draft
    raw = '1000 сум.\n```json\n' + json.dumps({'text': 'see above', 'coverage': [], 'metrics': {}}) + '\n```\nОснование: deals'
    draft = parse_draft(raw)
    assert 'metrics' not in draft.text
    assert '1000 сум' in draft.text and 'Основание' in draft.text


def test_explicit_money_cell_can_be_bound_to_scaled_display_without_requery():
    metric = claim(source={'evidence_id': 'e2', 'row': 0, 'column': 'deposit_uzs'})
    metric.update(value='1.5381', unit='trln UZS')
    evidence = [{'evidence_id': 'e2', 'rows': [{'deposit_uzs': '1538095229303.44'}]}]
    assert verify_metrics({'deposit': metric}, evidence)
    assert metric['value'] == '1538095229303.44'
    assert metric['unit'] == 'UZS'


def test_same_digits_do_not_justify_wrong_monetary_scale():
    metric = claim(source={'evidence_id': 'e2', 'row': 0, 'column': 'total_uzs'})
    metric.update(value='1000', unit='trln UZS')
    assert not verify_metrics({'total': metric}, [{'evidence_id': 'e2', 'rows': [{'total_uzs': '1000'}]}])


def test_currency_suffix_on_count_column_is_not_necessarily_money():
    metric = claim(source={'evidence_id': 'e2', 'row': 0, 'column': 'unused_uzs'})
    metric.update(value='127', unit='contracts')
    assert verify_metrics({'unused': metric}, [{'evidence_id': 'e2', 'rows': [{'unused_uzs': 127}]}])


def test_numeric_json_serialization_has_at_most_one_ulp_leeway():
    metric = claim(source={'evidence_id': 'e2', 'row': 0, 'column': 'amount_uzs'})
    metric.update(value=14.738418674737604, unit='trln UZS')
    assert verify_metrics({'amount': metric}, [{'evidence_id': 'e2', 'rows': [{'amount_uzs': '14738418674737.604900'}]}])


def test_missing_declared_output_is_marked_unresolved():
    import json
    from services.answer_contract import parse_draft
    draft = parse_draft(json.dumps({'text': 'Answer', 'analysis': {
        'requested_outputs': ['count', 'profit'], 'state_basis': 'noncancelled'},
        'coverage': [{'request': 'count', 'status': 'answered'}]}))
    assert draft.analysis.snapshot_date == '2026-10-30'
    assert draft.coverage[-1]['request'] == 'profit'
    assert draft.coverage[-1]['status'] == 'unresolved'


def test_source_cell_must_belong_to_declared_entity_when_row_has_key():
    metric = claim(source={'evidence_id': 'e2', 'row': 0, 'column': 'total_uzs'})
    metric.update(entity='BK111')
    evidence = [{'evidence_id': 'e2', 'rows': [{'seller_broker': 'BK106', 'total_uzs': '1000'}]}]
    assert not verify_metrics({'broker': metric}, evidence)


def test_typed_tool_state_scope_cannot_be_relabelled():
    metric = claim(source={'evidence_id': 'e2', 'row': 0, 'column': 'total'})
    evidence = [{'evidence_id': 'e2', 'scope': {'basis': 'completed'}, 'rows': [{'total': '1000'}]}]
    assert not verify_metrics({'total': metric}, evidence)
