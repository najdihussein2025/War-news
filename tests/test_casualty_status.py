from app.llm.dtos import ExtractionCasualties, VillageRoleEntry
from app.news.services.incident_details.casualty_status import (
    derive_casualty_status,
    merge_casualty_status,
    status_fields,
)


def test_no_casualty_words_is_none_mentioned() -> None:
    result = derive_casualty_status(
        "غارة إسرائيلية استهدفت منزلاً في كفررمان",
        ExtractionCasualties(),
        target_location_count=1,
    )

    assert result.status == "none_mentioned"
    assert result.deaths_status == result.injuries_status == "none_mentioned"


def test_obituary_and_page_header_do_not_create_count_missing() -> None:
    obituary = derive_casualty_status(
        "تنعى عائلة الشهيد علي الذي استشهد في وقت سابق",
        ExtractionCasualties(),
        target_location_count=1,
    )
    page_header = derive_casualty_status(
        "صفحة الإعلامي الشهيد علي شعيب\nغارة على منزل في كفررمان",
        ExtractionCasualties(),
        target_location_count=1,
    )

    assert obituary.status == "none_mentioned"
    assert page_header.status == "none_mentioned"


def test_explicit_none_is_distinct_from_no_mention() -> None:
    result = derive_casualty_status(
        "غارة على منزل غير مأهول دون تسجيل إصابات",
        ExtractionCasualties(injuries=0, total_injuries=0),
        target_location_count=1,
    )

    assert result.status == "explicit_none"
    assert result.injuries_status == "explicit_none"
    assert result.evidence == "دون تسجيل إصابات"


def test_bare_plural_and_vague_injury_wording_is_count_missing() -> None:
    for text in ("وقوع إصابات في غارة كفررمان", "استشهاد وإصابة مواطنين"):
        result = derive_casualty_status(
            text, ExtractionCasualties(), target_location_count=1
        )
        assert result.status == "count_missing"


def test_numberless_injury_phrases_keep_counts_null_and_are_not_dropped() -> None:
    for text in ("سقوط إصابات جراء القصف", "عدد من الجرحى جراء الغارة"):
        result = derive_casualty_status(
            text,
            ExtractionCasualties(),
            target_location_count=1,
        )
        assert result.status == "count_missing"
        assert result.injuries_status == "count_missing"


def test_dual_count_filled_for_one_location_is_exact() -> None:
    result = derive_casualty_status(
        "وزارة الصحة: شهيدان في غارة استهدفت دراجة نارية في كفررمان",
        ExtractionCasualties(deaths=2, total_deaths=2),
        village_roles=[VillageRoleEntry(village="كفررمان", deaths=2)],
        target_location_count=1,
    )

    assert result.status == "exact"
    assert result.deaths_status == "exact"
    assert result.injuries_status == "none_mentioned"


def test_multi_village_bare_casualty_words_are_count_missing() -> None:
    result = derive_casualty_status(
        "شهداء وجرحى في النبطية وصور",
        ExtractionCasualties(),
        target_location_count=2,
    )

    assert result.status == "count_missing"
    assert result.deaths_status == "count_missing"
    assert result.injuries_status == "count_missing"


def test_multi_village_total_without_breakdown_is_aggregate_only() -> None:
    result = derive_casualty_status(
        "5 شهداء و24 جريحاً في النبطية وصور والبقاع الغربي",
        ExtractionCasualties(total_deaths=5, total_injuries=24),
        target_location_count=3,
    )

    assert result.status == "aggregate_only"
    assert result.deaths_status == result.injuries_status == "aggregate_only"
    assert result.remaining_total == {"deaths": 5, "injuries": 24}


def test_known_location_counts_keep_remainder_of_larger_total() -> None:
    result = derive_casualty_status(
        "5 شهداء في النبطية وصور، حددت الوزارة اثنين في النبطية",
        ExtractionCasualties(total_deaths=5),
        village_roles=[VillageRoleEntry(village="النبطية", deaths=2)],
        target_location_count=2,
    )

    assert result.status == "aggregate_only"
    assert result.deaths_status == "aggregate_only"
    assert result.remaining_total == {"deaths": 3}


def test_per_location_breakdown_is_exact() -> None:
    result = derive_casualty_status(
        "شهيدان في النبطية وثلاثة شهداء في صور",
        ExtractionCasualties(),
        village_roles=[
            VillageRoleEntry(village="النبطية", deaths=2),
            VillageRoleEntry(village="صور", deaths=3),
        ],
        target_location_count=2,
    )

    assert result.status == "exact"
    assert result.deaths_status == "exact"
    assert result.remaining_total == {}


def test_preliminary_toll_is_an_overlay_only_when_tied_to_casualties() -> None:
    preliminary = derive_casualty_status(
        "4 جرحى في حصيلة أولية للغارة في صور",
        ExtractionCasualties(injuries=4),
        village_roles=[VillageRoleEntry(village="صور", injuries=4)],
        target_location_count=1,
    )
    strike_info = derive_casualty_status(
        "معلومات أولية عن غارة استهدفت مبنى في صور",
        ExtractionCasualties(),
        target_location_count=1,
    )
    final_toll = derive_casualty_status(
        "4 جرحى في حصيلة نهائية للغارة في صور",
        ExtractionCasualties(injuries=4),
        village_roles=[VillageRoleEntry(village="صور", injuries=4)],
        target_location_count=1,
    )

    assert preliminary.status == "exact"
    assert preliminary.is_preliminary is True
    assert strike_info.is_preliminary is False
    assert final_toll.is_preliminary is False


def test_update_and_revision_language_marks_a_casualty_toll_preliminary() -> None:
    result = derive_casualty_status(
        "تحديث الحصيلة: ارتفع عدد الشهداء إلى 3",
        ExtractionCasualties(deaths=3),
        target_location_count=1,
    )

    assert result.is_preliminary is True


def test_merge_status_exact_is_never_downgraded() -> None:
    merged = merge_casualty_status(
        "exact", False, "exact evidence", "count_missing", True, "vague evidence",
        incoming_is_newest=True,
    )
    assert merged == {
        "casualty_status": "exact",
        "casualty_is_preliminary": True,
        "casualty_status_evidence": "exact evidence",
    }


def test_merge_status_unmentioned_to_aggregate_and_preliminary_clears() -> None:
    aggregate = merge_casualty_status(
        "none_mentioned", False, None, "aggregate_only", True, "aggregate sentence",
        incoming_is_newest=True,
    )
    final = merge_casualty_status(
        "exact", True, "initial toll", "exact", False, "final toll",
        incoming_is_newest=True,
    )
    assert aggregate["casualty_status"] == "aggregate_only"
    assert final["casualty_is_preliminary"] is False
    assert final["casualty_status_evidence"] == "final toll"


def test_merge_preserves_and_updates_type_statuses_and_remaining_total() -> None:
    merged = merge_casualty_status(
        "exact",
        False,
        "known figures",
        "aggregate_only",
        False,
        "aggregate bulletin",
        incoming_is_newest=True,
        current_deaths_status="exact",
        incoming_deaths_status="aggregate_only",
        current_injuries_status="exact",
        incoming_injuries_status="count_missing",
        current_remaining_total={},
        incoming_remaining_total={"deaths": 2},
    )

    assert merged["casualty_deaths_status"] == "exact"
    assert merged["casualty_injuries_status"] == "count_missing"
    assert merged["casualty_status_remaining_total"] == {"deaths": 2}


def test_status_fields_include_persistable_type_statuses() -> None:
    result = derive_casualty_status(
        "أدى القصف إلى شهيد وجرحى",
        {"deaths": 1, "injuries": None},
        target_location_count=1,
    )

    fields = status_fields(result)
    assert fields["casualty_deaths_status"] == "exact"
    assert fields["casualty_injuries_status"] == "count_missing"
    assert fields["casualty_status_remaining_total"] == {}
