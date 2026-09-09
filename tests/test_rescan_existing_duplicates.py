from datetime import date, time
from uuid import UUID

from app.news.services.dedup.duplicate_comparison_service import (
    DuplicateComparisonConfig,
    DuplicateComparisonService,
)
from scripts.review.rescan_existing_duplicates import ScanIncident, scan_incidents


COMPARISON = DuplicateComparisonService(
    DuplicateComparisonConfig(
        lookup_window_days=7,
        gap_near_seconds=120,
        gap_mid_seconds=1_800,
        gap_far_seconds=21_600,
        text_near=0.38,
        text_mid=0.65,
        text_high=0.80,
        embedding_possible=0.78,
        embedding_high=0.86,
    )
)


def _incident(
    number: int,
    *,
    event_day: int = 1,
    event_minute: int = 0,
    embedding: list[float] | None = None,
    verification_status: str = "auto_processed",
) -> ScanIncident:
    return ScanIncident(
        id=UUID(int=number),
        village_id=10,
        condition_id=20,
        village="Khiyam",
        condition="Shelling",
        event_date=date(2026, 9, event_day),
        event_time=time(9, event_minute),
        khabar=f"incident {number}",
        khabar_embedding=embedding,
        duplicate_flag=False,
        verification_status=verification_status,
    )


def test_scan_identifies_possible_duplicate_from_embedding() -> None:
    result = scan_incidents(
        [
            _incident(1, embedding=[1.0, 0.0]),
            _incident(2, event_minute=5, embedding=[0.8, 0.6]),
        ],
        comparison=COMPARISON,
        lookup_window_days=7,
    )

    assert result.pairs_evaluated == 1
    assert result.verdict_counts["possible_duplicate"] == 1
    assert len(result.plans) == 1
    assert result.plans[0].earlier.id == UUID(int=1)
    assert result.plans[0].later.id == UUID(int=2)
    assert result.plans[0].embedding_similarity == 0.8


def test_scan_uses_verified_earlier_incident_as_candidate() -> None:
    result = scan_incidents(
        [
            _incident(
                1,
                embedding=[1.0, 0.0],
                verification_status="verified",
            ),
            _incident(2, event_minute=5, embedding=[1.0, 0.0]),
        ],
        comparison=COMPARISON,
        lookup_window_days=7,
    )

    assert result.pairs_evaluated == 1
    assert len(result.plans) == 1
    assert result.plans[0].earlier.id == UUID(int=1)
    assert result.plans[0].duplicate_level == "high"


def test_scan_skips_pair_with_rejected_incident() -> None:
    result = scan_incidents(
        [
            _incident(
                1,
                embedding=[1.0, 0.0],
                verification_status="rejected",
            ),
            _incident(2, event_minute=5, embedding=[1.0, 0.0]),
        ],
        comparison=COMPARISON,
        lookup_window_days=7,
    )

    assert result.pairs_evaluated == 0
    assert result.plans == []


def test_scan_skips_pair_outside_lookup_window() -> None:
    result = scan_incidents(
        [
            _incident(1, event_day=1, embedding=[1.0, 0.0]),
            _incident(2, event_day=9, embedding=[1.0, 0.0]),
        ],
        comparison=COMPARISON,
        lookup_window_days=7,
    )

    assert result.pairs_evaluated == 0
    assert result.plans == []


def test_scan_counts_pair_with_missing_embedding() -> None:
    result = scan_incidents(
        [
            _incident(1, embedding=None),
            _incident(2, event_minute=5, embedding=[1.0, 0.0]),
        ],
        comparison=COMPARISON,
        lookup_window_days=7,
    )

    assert result.pairs_evaluated == 0
    assert result.skipped_missing_embedding == 1


def test_scan_flags_later_incident_against_closest_matching_candidate() -> None:
    result = scan_incidents(
        [
            _incident(1, event_minute=0, embedding=[1.0, 0.0]),
            _incident(2, event_minute=5, embedding=[0.0, 1.0]),
            _incident(3, event_minute=10, embedding=[0.0, 1.0]),
        ],
        comparison=COMPARISON,
        lookup_window_days=7,
    )

    plan_for_latest = next(
        plan for plan in result.plans if plan.later.id == UUID(int=3)
    )
    assert plan_for_latest.earlier.id == UUID(int=2)
