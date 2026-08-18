from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.news.services.fast_path_dedup import (
    FastPathDedupOutcome,
    FastPathDedupService,
)


class _IncidentRepoStub:
    def __init__(self, existing=None) -> None:
        self.existing = existing
        self.last_query: dict | None = None

    def find_active_incident_in_fast_dedup_window(self, **kwargs):
        self.last_query = kwargs
        return self.existing


def test_confident_duplicate_when_high_confidence_match_in_window() -> None:
    existing = SimpleNamespace(
        id=uuid4(),
        raw_message_id=100,
    )
    repo = _IncidentRepoStub(existing=existing)
    service = FastPathDedupService(repo)

    decision = service.decide_for_village(
        village_match_status="matched",
        condition_match_status="matched",
        village_id=42,
        condition_id=7,
        message_datetime=datetime(2026, 8, 18, 11, 0, tzinfo=timezone.utc),
        exclude_raw_message_id=200,
    )

    assert decision.outcome == FastPathDedupOutcome.confident_duplicate
    assert decision.representative_raw_message_id == 100
    assert repo.last_query == {
        "village_id": 42,
        "condition_id": 7,
        "message_datetime": datetime(2026, 8, 18, 11, 0, tzinfo=timezone.utc),
        "window_minutes": 120,
        "exclude_raw_message_id": 200,
    }


def test_materialize_when_no_existing_incident_in_window() -> None:
    repo = _IncidentRepoStub(existing=None)
    service = FastPathDedupService(repo)

    decision = service.decide_for_village(
        village_match_status="matched",
        condition_match_status="matched",
        village_id=42,
        condition_id=7,
        message_datetime=datetime(2026, 8, 18, 11, 0, tzinfo=timezone.utc),
    )

    assert decision.outcome == FastPathDedupOutcome.materialize


def test_materialize_on_low_confidence_village_even_when_window_match_exists() -> None:
    existing = SimpleNamespace(id=uuid4(), raw_message_id=100)
    repo = _IncidentRepoStub(existing=existing)
    service = FastPathDedupService(repo)

    decision = service.decide_for_village(
        village_match_status="matched_low_confidence",
        condition_match_status="matched",
        village_id=42,
        condition_id=7,
        message_datetime=datetime(2026, 8, 18, 11, 0, tzinfo=timezone.utc),
    )

    assert decision.outcome == FastPathDedupOutcome.materialize


def test_skip_ineligible_when_village_unmatched() -> None:
    repo = _IncidentRepoStub()
    service = FastPathDedupService(repo)

    decision = service.decide_for_village(
        village_match_status="unmatched",
        condition_match_status="matched",
        village_id=None,
        condition_id=7,
        message_datetime=datetime(2026, 8, 18, 11, 0, tzinfo=timezone.utc),
    )

    assert decision.outcome == FastPathDedupOutcome.skip_ineligible
    assert repo.last_query is None
