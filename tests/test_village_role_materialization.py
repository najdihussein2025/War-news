from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401

from app.news.models import Incident, MessageStatus
from app.news.services.fast_path_dedup import FastPathDedupOutcome
from app.news.services.fast_path_eligibility import has_materializable_village
from app.news.services.incident_materialization_service import (
    IncidentMaterializationService,
)


class _SessionStub:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.staged: list[object] = []
        self.committed: list[object] = []
        self.flush_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0

    def add(self, value: object) -> None:
        self.added.append(value)
        self.staged.append(value)

    def flush(self) -> None:
        self.flush_calls += 1
        incident = next(
            (value for value in self.staged if isinstance(value, Incident)),
            None,
        )
        if incident is not None and incident.id is None:
            incident.id = uuid4()

    def commit(self) -> None:
        self.commit_calls += 1
        self.committed.extend(self.staged)
        self.staged.clear()

    def rollback(self) -> None:
        self.rollback_calls += 1
        self.staged.clear()

    def scalar(self, _statement):
        return None

    def execute(self, _statement, _params=None):
        return None


def _extraction_result() -> dict:
    return {
        "is_relevant": True,
        "village": ["البياض", "المنصوري"],
        "village_roles": [
            {"village": "البياض", "role": "origin"},
            {"village": "المنصوري", "role": "target"},
        ],
        "action_description": "قصف مدفعي",
        "categories": {},
        "casualties": {
            "deaths": 1,
            "injuries": 2,
        },
        "casualty_transitions": [],
        "model": "test-model",
        "extracted_at": "2026-09-03T08:00:00Z",
    }


def _match_result() -> dict:
    return {
        "village_matches": [
            {
                "raw_village_text": "البياض",
                "matched_village_id": 975,
                "village_confidence": 1.0,
                "village_match_status": "matched",
                "village_review_required": False,
                "village_role": "origin",
            },
            {
                "raw_village_text": "المنصوري",
                "matched_village_id": 976,
                "village_confidence": 1.0,
                "village_match_status": "matched",
                "village_review_required": False,
                "village_role": "target",
            },
        ],
        "any_village_low_confidence": False,
        "raw_condition_text": "قصف مدفعي",
        "condition_confidence": 0.8,
        "matched_condition_id": 5,
        "condition_match_status": "matched",
        "condition_review_required": False,
    }


def _multi_target_match_result() -> dict:
    return {
        "village_matches": [
            {
                "raw_village_text": "المنصوري",
                "matched_village_id": 976,
                "village_confidence": 1.0,
                "village_match_status": "matched",
                "village_review_required": False,
                "village_role": "target",
            },
            {
                "raw_village_text": "مجدل زون",
                "matched_village_id": 977,
                "village_confidence": 1.0,
                "village_match_status": "matched",
                "village_review_required": False,
                "village_role": "target",
            },
        ],
        "any_village_low_confidence": False,
        "raw_condition_text": "قصف مدفعي",
        "condition_confidence": 0.8,
        "matched_condition_id": 5,
        "condition_match_status": "matched",
        "condition_review_required": False,
    }


def _representative(match_result: dict, extraction_result: dict | None = None):
    return SimpleNamespace(
        id=42,
        source_id=9,
        raw_text="خبر عاجل",
        message_datetime=datetime(2026, 9, 3, 12, 30, tzinfo=timezone.utc),
        content_embedding=[0.1, 0.2, 0.3],
        extraction_result=extraction_result or _extraction_result(),
        match_result=match_result,
        status=MessageStatus.parsed,
        error_message=None,
        fast_path_completed_at=None,
        tier2_completed_at=None,
        embedded_at=None,
        materialized_at=None,
    )


def test_origin_village_does_not_materialize_separate_incident() -> None:
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]

    result = service.materialize(_representative(_match_result()))

    assert len(result) == 1
    incident = result[0]
    assert incident.village_id == 976
    assert incident.note == "Origin village: البياض"


def test_genuine_multi_target_strike_still_materializes_multiple_incidents() -> None:
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]
    extraction = _extraction_result()
    extraction["village"] = ["المنصوري", "مجدل زون"]
    extraction["village_roles"] = [
        {"village": "المنصوري", "role": "target"},
        {"village": "مجدل زون", "role": "target"},
    ]

    result = service.materialize(
        _representative(_multi_target_match_result(), extraction_result=extraction)
    )

    assert len(result) == 2
    assert {incident.village_id for incident in result} == {976, 977}
    assert all(incident.note is None for incident in result)


def test_fast_path_ignores_origin_only_village_when_materializing() -> None:
    db = _SessionStub()
    service = IncidentMaterializationService(db)  # type: ignore[arg-type]

    result = service.process_fast_path(
        _representative(_match_result()),
        SimpleNamespace(
            decide_for_village=lambda **_kwargs: SimpleNamespace(
                outcome=FastPathDedupOutcome.materialize,
                representative_raw_message_id=None,
                canonical_incident_id=None,
            )
        ),
    )

    assert len(result) == 1
    assert result[0].village_id == 976
    assert result[0].note == "Origin village: البياض"


def test_has_materializable_village_excludes_origin_only_matches() -> None:
    match_result = {
        "village_matches": [
            {
                "raw_village_text": "البياض",
                "matched_village_id": 975,
                "village_match_status": "matched",
                "village_role": "origin",
            }
        ]
    }

    assert has_materializable_village(match_result) is False
