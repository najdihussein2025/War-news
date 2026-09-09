"""Casualty count backstop: vague quantifiers and missing evidence_span."""

from __future__ import annotations

import logging

from app.llm.dtos import CasualtyCountEvidence, ExtractionCasualties
from app.news.services.incident_details.casualty_count_backstop import (
    apply_casualty_count_backstop,
)


def test_dozens_injured_with_children_mention_is_nulled() -> None:
    """4105/4121-style: عشرات الجرحى بينهم أطفال ونساء must not fabricate counts."""
    text = (
        "عشرات الجرحى، بينهم أطفال ونساء، جراء غارة استهدفت منزلًا خاليًا "
        "في حي سكني ببلدة الرمادية، قضاء صور."
    )
    casualties = ExtractionCasualties(injuries=10, children_injuries=6)
    evidence = [
        CasualtyCountEvidence(field="injuries", evidence_span="عشرات الجرحى"),
        CasualtyCountEvidence(field="children_injuries", evidence_span="بينهم أطفال"),
    ]

    result, kept = apply_casualty_count_backstop(
        text,
        casualties,
        evidence,
        raw_message_id=4105,
    )

    assert result.injuries is None
    assert result.children_injuries is None
    assert kept == []


def test_number_of_martyrs_vague_phrase_is_nulled() -> None:
    """4396-style: عدد من الشهداء must not become a fabricated death count."""
    text = "سقوط عدد من الشهداء من عائلة واحدة في كفررمان"
    result, kept = apply_casualty_count_backstop(
        text,
        ExtractionCasualties(deaths=4),
        [CasualtyCountEvidence(field="deaths", evidence_span="عدد من الشهداء")],
        raw_message_id=4396,
    )

    assert result.deaths is None
    assert kept == []


def test_number_of_injuries_vague_phrase_stays_null() -> None:
    """4005-style: عدد من الإصابات already null — stays null."""
    text = "لبنان: مراسل الميادين: عدد من الإصابات في غارات إسرائيلية على حي الراهبات"
    result, kept = apply_casualty_count_backstop(
        text,
        ExtractionCasualties(),
        [],
        raw_message_id=4005,
    )

    assert result == ExtractionCasualties()
    assert kept == []


def test_explicit_digit_counts_are_preserved_with_evidence() -> None:
    text = "4 قتلى و10 جرحى في غارة على البلدة"
    evidence = [
        CasualtyCountEvidence(field="deaths", evidence_span="4 قتلى"),
        CasualtyCountEvidence(field="injuries", evidence_span="10 جرحى"),
    ]

    result, kept = apply_casualty_count_backstop(
        text,
        ExtractionCasualties(deaths=4, injuries=10),
        evidence,
        raw_message_id=99,
    )

    assert result.deaths == 4
    assert result.injuries == 10
    assert {item.field for item in kept} == {"deaths", "injuries"}


def test_arabic_indic_digit_counts_are_preserved() -> None:
    text = "٤ شهداء و١٠ جرحى"
    evidence = [
        CasualtyCountEvidence(field="deaths", evidence_span="٤ شهداء"),
        CasualtyCountEvidence(field="injuries", evidence_span="١٠ جرحى"),
    ]

    result, kept = apply_casualty_count_backstop(
        text,
        ExtractionCasualties(deaths=4, injuries=10),
        evidence,
        raw_message_id=100,
    )

    assert result.deaths == 4
    assert result.injuries == 10
    assert len(kept) == 2


def test_explicit_arabic_singular_and_dual_counts_are_preserved() -> None:
    text = "الرمادية: شهيد وجريح، كفرمان: شهيدان"
    result, kept = apply_casualty_count_backstop(
        text,
        ExtractionCasualties(deaths=2, injuries=1),
        [
            CasualtyCountEvidence(field="deaths", evidence_span="شهيدان"),
            CasualtyCountEvidence(field="injuries", evidence_span="جريح"),
        ],
    )

    assert result.deaths == 2
    assert result.injuries == 1
    assert {item.field for item in kept} == {"deaths", "injuries"}


def test_casualty_digit_must_appear_inside_grounded_evidence_span() -> None:
    text = "البلدة الأولى: 4 جرحى، البلدة الثانية: عشرات الجرحى"
    result, kept = apply_casualty_count_backstop(
        text,
        ExtractionCasualties(injuries=4),
        [
            CasualtyCountEvidence(
                field="injuries",
                evidence_span="البلدة الثانية: عشرات الجرحى",
            )
        ],
    )

    assert result.injuries is None
    assert kept == []


def test_missing_evidence_span_nulls_count_and_logs_warning(caplog) -> None:
    text = "4 قتلى و10 جرحى في غارة على البلدة"

    with caplog.at_level(logging.WARNING):
        result, kept = apply_casualty_count_backstop(
            text,
            ExtractionCasualties(deaths=4, injuries=10),
            [
                CasualtyCountEvidence(field="deaths", evidence_span="4 قتلى"),
                # injuries intentionally missing evidence_span
            ],
            raw_message_id=777,
        )

    assert result.deaths == 4
    assert result.injuries is None
    assert [item.field for item in kept] == ["deaths"]
    assert any(
        "casualty_count_backstop nulled field=injuries" in record.message
        and "missing_evidence_span" in record.message
        and "raw_message_id=777" in record.message
        for record in caplog.records
    )


def test_evidence_present_but_digit_absent_is_nulled(caplog) -> None:
    text = "عشرات الجرحى في البلدة"

    with caplog.at_level(logging.WARNING):
        result, kept = apply_casualty_count_backstop(
            text,
            ExtractionCasualties(injuries=10),
            [CasualtyCountEvidence(field="injuries", evidence_span="عشرات الجرحى")],
            raw_message_id=4121,
        )

    assert result.injuries is None
    assert kept == []
    assert any(
        "digit_not_in_source" in record.message and "raw_message_id=4121" in record.message
        for record in caplog.records
    )


def test_dozens_of_injured_and_martyrs_never_becomes_ten() -> None:
    text = "عشرات الجرحى والشهداء جراء الغارة على البلدة"
    evidence = [
        CasualtyCountEvidence(
            field=field,
            evidence_span="عشرات الجرحى والشهداء",
        )
        for field in ("deaths", "injuries", "total_deaths", "total_injuries")
    ]

    result, kept = apply_casualty_count_backstop(
        text,
        ExtractionCasualties(
            deaths=10,
            injuries=10,
            total_deaths=10,
            total_injuries=10,
        ),
        evidence,
    )

    assert result == ExtractionCasualties()
    assert kept == []
