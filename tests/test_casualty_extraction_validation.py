from app.llm.dtos import CasualtyCountEvidence, ExtractionCasualties
from app.news.services.incident_details.casualty_extraction_validation import (
    enforce_casualty_invariants,
    validate_casualty_evidence,
)
from app.news.services.incident_details.casualty_gender_evidence import (
    reject_unproven_demographics,
)
from app.news.services.incident_details.casualty_status import derive_casualty_status


def test_header_evidence_is_dropped_from_cleaned_body():
    values, evidence, dropped = validate_casualty_evidence(
        "قصف مدفعي يستهدف المنصوري",
        ExtractionCasualties(deaths=1, total_deaths=1),
        [CasualtyCountEvidence(field="deaths", evidence_span="صفحة الإعلامي الشهيد علي شعيب")],
    )
    assert values.deaths is None and values.total_deaths is None
    assert evidence == []
    assert dropped[0]["reason"] == "evidence_not_in_cleaned_body"


def test_memorial_evidence_is_dropped_even_if_present_in_body():
    values, _, dropped = validate_casualty_evidence(
        "في ذكرى الشهيد علي شعيب رحم الله الشهداء",
        ExtractionCasualties(deaths=1, total_deaths=1),
        [CasualtyCountEvidence(field="deaths", evidence_span="في ذكرى الشهيد علي شعيب")],
    )
    assert values.deaths is None
    assert dropped[0]["reason"] == "header_or_memorial_evidence"


def test_untyped_three_deaths_retains_total_and_no_breakdown():
    values, adjustments = enforce_casualty_invariants(
        ExtractionCasualties(deaths=3, total_deaths=3, male_deaths=3),
        evidence_fields={"deaths"},
    )
    assert values.total_deaths == 3
    assert values.male_deaths is None
    assert adjustments[0]["reason"] == "untyped_count_breakdown_dropped"


def test_child_precedence_is_preserved_by_untyped_guard():
    values, _ = enforce_casualty_invariants(
        ExtractionCasualties(deaths=1, total_deaths=1, children_deaths=1, female_deaths=1),
        evidence_fields={"deaths", "children_deaths"},
    )
    assert values.children_deaths == 1
    assert values.female_deaths is None


def test_martyred_girl_is_children_not_female():
    values = reject_unproven_demographics(
        "استشهاد طفلة",
        ExtractionCasualties(deaths=1, total_deaths=1, children_deaths=1, female_deaths=1),
    )
    assert values.children_deaths == 1
    assert values.female_deaths is None


def test_breakdown_sum_raises_total_and_negative_is_dropped():
    values, adjustments = enforce_casualty_invariants(
        ExtractionCasualties(total_injuries=1, male_injuries=1, children_injuries=2, female_injuries=-1)
    )
    assert values.total_injuries == 3
    assert values.female_injuries is None
    assert {item["reason"] for item in adjustments} == {"negative_count_dropped", "raised_to_breakdown_sum"}


def test_numberless_injury_status_survives_validation():
    values, _, dropped = validate_casualty_evidence(
        "سقوط إصابات جراء القصف",
        ExtractionCasualties(),
        [],
    )
    status = derive_casualty_status("سقوط إصابات جراء القصف", values, target_location_count=1)
    assert values.injuries is None and values.total_injuries is None
    assert dropped == []
    assert status.status == status.injuries_status == "count_missing"
