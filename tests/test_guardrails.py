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
    evidence = make_evidence('{"deal_date": "2023-01-02"}')
    answer = "📊 Сделка от 02.01.2023.\n\nОснование: deals_enriched; deal_no=1."
    result = verify_answer(answer, evidence, "ru")
    assert result.ok, result


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


def test_tiny_numbers_are_ignored() -> None:
    result = verify_answer("📊 2 сделки.\n\nОснование: deals_enriched.", EvidenceIndex(), "ru")
    assert result.ok


def test_extract_candidates_does_not_split_date() -> None:
    candidates = extract_candidates("02.01.2023 и 2024-05-06")
    dates = [candidate.variants for candidate in candidates if candidate.kind == "date"]
    assert frozenset({"20230102"}) in dates
    assert frozenset({"20240506"}) in dates


def test_footer_is_bilingual() -> None:
    assert "Основание" in format_evidence_footer("ru", ["deals_enriched"], 2, 10)
    assert "Asos" in format_evidence_footer("uz", ["deals_enriched"], 2, 10)
