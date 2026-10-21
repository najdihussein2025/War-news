from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.news.models import RawMessage
from app.news.services.dedup.fast_path_eligibility import (
    ERROR_AIR_VIOLATION,
    ERROR_NO_VILLAGE,
    ERROR_UNMATCHED_CONDITION,
    FAST_PATH_MATERIALIZABLE_SQL,
    fast_path_materializable_clause,
    permanent_ineligibility_reason,
)


def test_permanent_ineligibility_unmatched_condition() -> None:
    assert (
        permanent_ineligibility_reason(
            {
                "condition_match_status": "unmatched",
                "village_matches": [
                    {
                        "matched_village_id": 1,
                        "village_match_status": "matched",
                    }
                ],
            }
        )
        == ERROR_UNMATCHED_CONDITION
    )


def test_permanent_ineligibility_air_violation() -> None:
    assert (
        permanent_ineligibility_reason(
            {
                "condition_match_status": "matched",
                "matched_condition_id": 35,
                "village_matches": [
                    {
                        "matched_village_id": 1,
                        "village_match_status": "matched",
                    }
                ],
            }
        )
        == ERROR_AIR_VIOLATION
    )

    assert (
        permanent_ineligibility_reason(
            {
                "condition_match_status": "matched",
                "matched_condition_id": 45,
                "village_matches": [],
            }
        )
        == ERROR_NO_VILLAGE
    )


def test_permanent_ineligibility_empty_villages() -> None:
    assert (
        permanent_ineligibility_reason(
            {
                "condition_match_status": "matched",
                "matched_condition_id": 5,
                "village_matches": [],
            }
        )
        == ERROR_NO_VILLAGE
    )


def test_permanent_ineligibility_none_when_materializable() -> None:
    assert (
        permanent_ineligibility_reason(
            {
                "condition_match_status": "matched_low_confidence",
                "matched_condition_id": 1,
                "village_matches": [
                    {
                        "matched_village_id": 42,
                        "village_match_status": "matched",
                    }
                ],
            }
        )
        is None
    )


def test_event_condition_can_materialize_when_root_condition_is_unmatched() -> None:
    assert (
        permanent_ineligibility_reason(
            {
                "condition_match_status": "unmatched",
                "matched_condition_id": None,
                "village_matches": [
                    {
                        "matched_village_id": 42,
                        "village_match_status": "matched",
                        "matched_condition_id": 8,
                        "condition_match_status": "matched",
                        "event_index": 0,
                    }
                ],
            }
        )
        is None
    )


def test_root_condition_fallback_when_village_conditions_unmatched() -> None:
    """ACCSTUDY-003/005: sub-event conditions unmatched but root Bombs matched."""
    assert (
        permanent_ineligibility_reason(
            {
                "condition_match_status": "matched",
                "matched_condition_id": 1,
                "village_matches": [
                    {
                        "matched_village_id": 701,
                        "village_match_status": "matched",
                        "matched_condition_id": None,
                        "condition_match_status": "unmatched",
                        "event_index": 0,
                    },
                    {
                        "matched_village_id": 994,
                        "village_match_status": "matched",
                        "matched_condition_id": None,
                        "condition_match_status": "unmatched",
                        "event_index": 1,
                    },
                ],
            }
        )
        is None
    )


def test_claim_sql_excludes_air_violations_and_requires_village() -> None:
    compiled = str(
        select(RawMessage)
        .where(fast_path_materializable_clause())
        .compile(dialect=postgresql.dialect())
    )
    assert "NOT IN (34, 35, 36, 38)" in compiled
    assert "village_matches" in compiled
    assert "matched_low_confidence" in compiled
    assert FAST_PATH_MATERIALIZABLE_SQL.strip() in compiled or "village_matches" in compiled


def test_unmatched_named_place_is_held_not_errored() -> None:
    # raw_message 29077: «قصف مدفعي يستهدف وادي الحجير لجهة بلدة الغندورية»,
    # the place was missing from the gazetteer/aliases and the row was lost.
    from app.news.models import MessageStatus
    from app.news.services.dedup.fast_path_eligibility import (
        HELD_UNMATCHED_PLACE,
        terminal_status_for_reason,
        unmatched_target_places,
    )

    match_result = {
        "condition_match_status": "matched",
        "matched_condition_id": 5,
        "village_matches": [
            {
                "raw_village_text": "الغندورية",
                "matched_village_id": None,
                "village_match_status": "unmatched",
                "village_role": "target",
            }
        ],
    }

    reason = permanent_ineligibility_reason(match_result)

    assert reason == HELD_UNMATCHED_PLACE
    assert terminal_status_for_reason(reason) == MessageStatus.held_for_review
    assert unmatched_target_places(match_result) == ["الغندورية"]


def test_origin_only_unmatched_place_is_not_held() -> None:
    reason = permanent_ineligibility_reason(
        {
            "condition_match_status": "matched",
            "matched_condition_id": 5,
            "village_matches": [
                {
                    "raw_village_text": "حداثا",
                    "matched_village_id": None,
                    "village_match_status": "unmatched",
                    "village_role": "origin",
                }
            ],
        }
    )

    assert reason == ERROR_NO_VILLAGE


def test_terminal_status_mapping_keeps_existing_statuses() -> None:
    from app.news.models import MessageStatus
    from app.news.services.dedup.fast_path_eligibility import terminal_status_for_reason

    assert terminal_status_for_reason(ERROR_AIR_VIOLATION) == MessageStatus.routed_air_violation
    assert terminal_status_for_reason(ERROR_NO_VILLAGE) == MessageStatus.error
    assert terminal_status_for_reason(ERROR_UNMATCHED_CONDITION) == MessageStatus.error


def test_kinetic_air_match_is_not_terminalized_as_air_violation() -> None:
    match_result = {
        "condition_match_status": "matched",
        "matched_condition_id": 38,
        "village_matches": [],
    }

    assert permanent_ineligibility_reason(
        match_result,
        "مروحية أباتشي استهدفت مبنى في ميفدون",
    ) is None


def test_presence_only_air_match_remains_terminal_air_violation() -> None:
    match_result = {
        "condition_match_status": "matched",
        "matched_condition_id": 36,
        "village_matches": [],
    }

    assert permanent_ineligibility_reason(
        match_result,
        "طيران مسير يحلق فوق صور",
    ) == ERROR_AIR_VIOLATION


def test_bulk_terminalize_sql_holds_unmatched_places() -> None:
    from app.news.services.dedup.fast_path_eligibility import (
        HELD_UNMATCHED_PLACE,
        ineligible_fast_path_update_sql,
    )

    statement = ineligible_fast_path_update_sql()
    sql = str(statement)
    params = statement.compile().params

    assert ":held_status" in sql
    assert "village_match_status' = 'unmatched'" in sql
    assert params["held_status"] == "held_for_review"
    assert params["held_unmatched_place"] == HELD_UNMATCHED_PLACE
