from __future__ import annotations

from services.guardrails import (
    EvidenceIndex,
    extract_candidates,
    format_evidence_footer,
    is_no_answer,
    number_variants,
    verify_answer,
)


def make_evidence(*texts: str) -> EvidenceIndex:
    index = EvidenceIndex()
    for text in texts:
        index.add(text)
    return index


def test_grouped_number_variants() -> None:
    assert "131895492" in number_variants("131 895 492")
    assert "131895492" in number_variants("131,895,492")
    assert "131895492" in number_variants("131.895.492")


def test_decimal_comma_and_dot_match() -> None:
    variants = number_variants("12,5")
    assert "12.5" in variants
    assert number_variants("12.500000") & variants


def test_date_is_normalised_for_comparison() -> None:
    evidence = make_evidence('{"deal_date": "2023-01-02", "deal_no": 1}')
    answer = "📊 Сделка от 02.01.2023.\n\nОснование: deals_enriched; deal_no=1."
    result = verify_answer(answer, evidence, "ru")
    assert result.ok, result


def test_year_from_date_is_accepted() -> None:
    evidence = make_evidence("2024-01-01", '{"n": 10}')
    answer = "📊 В 2024 году было 10 сделок.\n\nОснование: deals_enriched; строк: 1."
    result = verify_answer(answer, evidence, "ru")
    assert result.ok, result


def test_year_not_in_evidence_is_rejected() -> None:
    evidence = make_evidence("2024-01-01")
    answer = "📊 В 2025 году было 10 сделок.\n\nОснование: deals_enriched; строк: 1."
    result = verify_answer(answer, evidence, "ru")
    assert not result.ok
    assert "2025" in result.unsupported_numbers


def test_hallucinated_number_is_rejected() -> None:
    evidence = make_evidence('{"rows": [{"n": 106647}]}')
    answer = "📊 Всего 106 648 сделок.\n\nОснование: deals_enriched; период 2024."
    result = verify_answer(answer, evidence, "ru")
    assert not result.ok
    assert "106 648" in result.unsupported_numbers


def test_number_from_tool_result_is_accepted() -> None:
    evidence = make_evidence('{"rows": [{"n": 106647}]}')
    answer = "📊 Всего 106 647 сделок.\n\nОснование: deals_enriched; строк: 1."
    result = verify_answer(answer, evidence, "ru")
    assert result.ok, result


def test_number_in_evidence_line_is_checked() -> None:
    evidence = make_evidence('{"rows": [{"n": 1}]}')
    answer = "📊 Ответ 1.\n\nОснование: deal_no=999999."
    result = verify_answer(answer, evidence, "ru")
    assert not result.ok
    assert "999999" in result.unsupported_numbers


def test_broker_code_is_checked() -> None:
    evidence = make_evidence('{"seller_broker": "BK062"}')
    good = verify_answer("📊 Брокер BK062.\n\nОснование: deals_enriched.", evidence, "ru")
    bad = verify_answer("📊 Брокер BK999.\n\nОснование: deals_enriched.", evidence, "ru")
    assert good.ok
    assert not bad.ok


def test_no_answer_is_always_accepted() -> None:
    result = verify_answer("В данных реестра ответа на этот вопрос нет.", EvidenceIndex(), "ru")
    assert result.ok and result.no_answer
    assert is_no_answer("Maʼlumotlar reyestrida bu savolga javob yoʻq.")


def test_company_name_context_is_checked() -> None:
    evidence = make_evidence('{"name": "Pudexiz Plast"}')
    good = verify_answer(
        "📊 Компания «Pudexiz Plast» — продавец.\n\nОснование: participants.",
        evidence,
        "ru",
    )
    bad = verify_answer(
        "📊 Компания «Узавтосаноат» — продавец.\n\nОснование: participants.",
        evidence,
        "ru",
    )
    assert good.ok, good
    assert not bad.ok
    assert good.unsupported_names == []


def test_small_factual_numbers_are_checked() -> None:
    result = verify_answer("📊 2 сделки.\n\nОснование: deals_enriched.", EvidenceIndex(), "ru")
    assert not result.ok


def test_extract_candidates_does_not_split_date() -> None:
    candidates = extract_candidates("02.01.2023 и 2024-05-06")
    dates = [candidate.variants for candidate in candidates if candidate.kind == "date"]
    assert frozenset({"20230102"}) in dates
    assert frozenset({"20240506"}) in dates


def test_footer_is_bilingual() -> None:
    assert "Основание" in format_evidence_footer("ru", ["deals_enriched"], 2, 10)
    assert "Asos" in format_evidence_footer("uz", ["deals_enriched"], 2, 10)


def test_rounded_decimal_and_scaled_value_are_supported():
    evidence = make_evidence('7704993702929.156', '3.9243')
    assert verify_answer('7 704 993 702 929,16 сум; 3,92 %', evidence, 'ru').ok
    assert verify_answer('7,705 трлн сум', evidence, 'ru').ok
    assert not verify_answer('7,706 трлн сум', evidence, 'ru').ok


def test_mixed_refusal_cannot_bypass_verification():
    result = verify_answer('999999999 сум. В данных реестра ответа на этот вопрос нет.',
                           EvidenceIndex(), 'ru')
    assert not result.ok
    assert not result.no_answer
    assert not is_no_answer('')


def test_decimal_digits_and_signs_do_not_alias():
    evidence = make_evidence('12.34', '-372.4')
    assert not verify_answer('1234 сум', evidence, 'ru').ok
    assert not verify_answer('+372.4 сум', evidence, 'ru').ok
    assert verify_answer('−372,4 сум', evidence, 'ru').ok


def test_identifiers_do_not_round():
    evidence = make_evidence('123456789')
    assert not verify_answer('ИНН 123456788', evidence, 'ru').ok


def test_tool_metadata_cannot_support_a_factual_claim():
    evidence = EvidenceIndex()
    evidence.add_result({'rows': [{'n': 5}], 'row_count': 99, 'evidence_id': 'e1'})
    assert not verify_answer('99 сделок', evidence, 'ru').ok
    assert verify_answer('5 сделок', evidence, 'ru').ok


def test_markdown_scales_and_inline_list_ordinals():
    evidence = make_evidence('7704993702929.156', '2330761', '1367297')
    assert verify_answer('**7,705** трлн сум', evidence, 'ru').ok
    assert verify_answer('1) Пшеница 2330761 т; 2) Цемент 1367297 т', evidence, 'ru').ok


def test_explicit_scaled_sql_column_supports_scaled_display():
    evidence = EvidenceIndex()
    evidence.add_result({'rows': [{'late_sup_trln': 7.705}]})
    assert verify_answer('7,705 трлн сум', evidence, 'ru').ok


def test_conversion_explanation_does_not_allow_arbitrary_small_counts():
    evidence = EvidenceIndex()
    assert verify_answer('Килограммы переведены делением на 1000.', evidence, 'ru').ok
    assert not verify_answer('Всего 1000 сделок.', evidence, 'ru').ok


def test_percent_formula_constant_is_not_a_measured_percentage():
    assert verify_answer('Отклонение = отношение × 100%.', EvidenceIndex(), 'ru').ok
    assert not verify_answer('Отклонение 100%.', EvidenceIndex(), 'ru').ok


def test_exclusive_calendar_bound_is_supported_not_observed():
    evidence = EvidenceIndex()
    evidence.add_query_scope("SELECT 1 FROM deals WHERE deal_date >= DATE '2024-01-01' AND deal_date < DATE '2025-01-01'")
    assert verify_answer('Период 01.01.2024–31.12.2024', evidence, 'ru').ok
    assert not verify_answer('Период до 31.12.2026', evidence, 'ru').ok


def test_money_may_round_to_whole_soum_but_identifiers_and_counts_cannot():
    evidence = make_evidence('1937572360573.0248', '1.9')
    assert verify_answer('1 937 572 360 573 сум', evidence, 'ru').ok
    assert not verify_answer('2 сделки', evidence, 'ru').ok
    table = '| Категория | Сумма, сум |\n|---|---|\n| A | 1 937 572 360 573 |'
    assert verify_answer(table, evidence, 'ru').ok


def test_requested_forecast_year_can_be_mentioned_without_becoming_fact():
    evidence = EvidenceIndex(); evidence.add_request('Оборот в 2027 году?')
    assert verify_answer('Оборот за запрошенный год (2027) неизвестен.', evidence, 'ru').ok
    assert not verify_answer('2027 сделок.', evidence, 'ru').ok
    assert not verify_answer('2027 сум.', evidence, 'ru').ok


def test_short_period_boundaries_are_dates_not_decimals():
    evidence = make_evidence('2026-01-01', '2026-10-30')
    assert verify_answer('Период 01.01–30.10', evidence, 'ru').ok
    assert not verify_answer('Период 01.01–31.10', evidence, 'ru').ok


def test_identifier_leading_zeroes_are_preserved():
    evidence = make_evidence('{"inn": "000123456"}')
    assert verify_answer('ИНН 000123456', evidence, 'ru').ok
    assert not verify_answer('ИНН 123456', evidence, 'ru').ok


def test_malformed_number_is_rejected_without_crashing():
    result = verify_answer('1.234.56 сум', EvidenceIndex(), 'ru')
    assert not result.ok


def test_verbose_conversion_formula_can_explain_lot_multiplication():
    text = 'Килограммы переведены в тонны делением объёма (количество лотов × лот) на 1000 в SQL.'
    assert verify_answer(text, EvidenceIndex(), 'ru').ok


def test_scale_token_before_scope_suffix_is_preserved():
    evidence = EvidenceIndex()
    evidence.add_result({'rows': [{'bn_uzs_all_states': 8832.24}]})
    assert verify_answer('8 832,24 млрд UZS', evidence, 'ru').ok


def test_numbered_body_with_identifiers_does_not_recheck_ordinal_as_fact():
    evidence = make_evidence('100001', '604956')
    assert verify_answer('1. Сделки: от №100001 до №604956.', evidence, 'ru').ok


def test_inline_ordinals_do_not_strip_year_or_day_before_parenthesis():
    evidence = make_evidence('2026-08-05', '2026-10-30')
    assert verify_answer('Заключен (с 05.08.2026) и оплачен (до 2026-10-30) по данным.', evidence, 'ru').ok
    assert not verify_answer('Всего (123456) сделок.', evidence, 'ru').ok


def test_requested_forecast_year_with_uzbek_suffix():
    evidence = EvidenceIndex(); evidence.add_request('2027-yil aylanmasi qancha?')
    assert verify_answer('2027-yil prognozi reyestrda yoʻq.', evidence, 'uz').ok
