from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.llm.dtos import ExtractionCasualties, ExtractionResult
from app.news.models import MessageStatus
from app.news.services.fast_path_dedup import (
    FastPathDedupOutcome,
    FastPathDedupService,
)
from app.news.services.incident_materialization_service import (
    IncidentMaterializationService,
)


def _raw_message(
    *,
    message_id: int = 1,
    match_result: dict,
    extraction_result: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=message_id,
        status=MessageStatus.parsed,
        duplicate_of_id=None,
        raw_text="قصف على بلدة",
        source_id=1,
        message_datetime=datetime(2026, 8, 18, 11, 0, tzinfo=timezone.utc),
        extraction_result=extraction_result
        or ExtractionResult(
            is_relevant=True,
            village=["كفركلا"],
            action_description="قصف",
            casualties=ExtractionCasualties(deaths=1),
            model="test",
            extracted_at=datetime(2026, 8, 18, 11, 0, tzinfo=timezone.utc),
            extraction_tier=1,
        ).model_dump(mode="json"),
        match_result=match_result,
        content_embedding=None,
    )


def test_process_fast_path_materializes_with_details_pending() -> None:
    db = MagicMock()
    db.commit = MagicMock()
    db.rollback = MagicMock()
    db.add = MagicMock()
    db.flush = MagicMock()

    incident = SimpleNamespace(id="incident-1")
    db.flush.side_effect = lambda: setattr(incident, "id", "incident-1")

    service = IncidentMaterializationService(db)
    dedup = FastPathDedupService(MagicMock())
    dedup.decide_for_village = MagicMock(
        return_value=SimpleNamespace(
            outcome=FastPathDedupOutcome.materialize,
            canonical_incident_id=None,
            representative_raw_message_id=None,
        )
    )

    message = _raw_message(
        match_result={
            "matched_condition_id": 10,
            "condition_match_status": "matched",
            "village_matches": [
                {
                    "matched_village_id": 42,
                    "village_match_status": "matched",
                }
            ],
        }
    )

    created = service.process_fast_path(message, dedup)

    assert len(created) == 1
    assert service.fast_stats.inserted == 1
    added_incident = db.add.call_args_list[0].args[0]
    assert added_incident.details_pending is True
    assert added_incident.village_id == 42


def test_process_fast_path_marks_message_duplicate_when_all_villages_duplicate() -> None:
    db = MagicMock()
    db.commit = MagicMock()
    db.rollback = MagicMock()

    service = IncidentMaterializationService(db)
    dedup = FastPathDedupService(MagicMock())
    dedup.decide_for_village = MagicMock(
        return_value=SimpleNamespace(
            outcome=FastPathDedupOutcome.confident_duplicate,
            canonical_incident_id="canonical",
            representative_raw_message_id=999,
        )
    )

    message = _raw_message(
        match_result={
            "matched_condition_id": 10,
            "condition_match_status": "matched",
            "village_matches": [
                {
                    "matched_village_id": 42,
                    "village_match_status": "matched",
                }
            ],
        }
    )

    created = service.process_fast_path(message, dedup)

    assert created == []
    assert message.status == MessageStatus.duplicate
    assert message.duplicate_of_id == 999
    assert service.fast_stats.marked_message_duplicate == 1
    db.commit.assert_called()


def test_process_fast_path_terminalizes_unmatched_condition() -> None:
    db = MagicMock()
    service = IncidentMaterializationService(db)
    message = _raw_message(
        match_result={
            "matched_condition_id": None,
            "condition_match_status": "unmatched",
            "village_matches": [],
        }
    )

    created = service.process_fast_path(message, FastPathDedupService(MagicMock()))

    assert created == []
    assert message.status == MessageStatus.error
    assert "unmatched or missing condition" in (message.error_message or "")
    assert service.fast_stats.marked_unmaterializable == 1


def test_process_fast_path_terminalizes_air_violation_route() -> None:
    db = MagicMock()
    service = IncidentMaterializationService(db)
    message = _raw_message(
        match_result={
            "matched_condition_id": 36,
            "condition_match_status": "matched",
            "village_matches": [
                {
                    "matched_village_id": 42,
                    "village_match_status": "matched",
                }
            ],
        }
    )

    created = service.process_fast_path(message, FastPathDedupService(MagicMock()))

    assert created == []
    assert message.status == MessageStatus.error
    assert "air_violations" in (message.error_message or "")
    assert service.fast_stats.skipped_air_violation_routed == 1
