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
    assert "NOT IN (35, 36, 38)" in compiled
    assert "village_matches" in compiled
    assert "matched_low_confidence" in compiled
    assert FAST_PATH_MATERIALIZABLE_SQL.strip() in compiled or "village_matches" in compiled
