from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.news.models import MessageStatus
from app.news.services.dedup.fast_path_dedup import FastPathDedupOutcome
from app.news.services.materialization.incident_materialization_service import (
    IncidentMaterializationService,
)


class _SessionStub:
    def execute(self, _statement, _params=None):
        return None

    def commit(self) -> None:
        pass


def test_fast_path_passes_stripped_text_to_duplicate_comparison() -> None:
    captured: dict = {}

    def decide_for_village(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(outcome=FastPathDedupOutcome.skip_ineligible)

    representative = SimpleNamespace(
        id=42,
        source_id=9,
        raw_text='"الوكالة الوطنية": تحرك للدبابات باتجاه الخيام',
        message_datetime=datetime(2026, 8, 17, 12, 30, tzinfo=timezone.utc),
        content_embedding=[0.1, 0.2, 0.3],
        extraction_result={
            "is_relevant": True,
            "village": ["الخيام"],
            "action_description": "تحرك دبابات",
            "categories": {},
            "casualties": {},
            "model": "test-model",
            "extracted_at": "2026-08-17T10:00:00Z",
        },
        match_result={
            "village_matches": [
                {
                    "raw_village_text": "الخيام",
                    "matched_village_id": 976,
                    "village_confidence": 1.0,
                    "village_match_status": "matched",
                    "village_review_required": False,
                }
            ],
            "matched_condition_id": 5,
            "condition_match_status": "matched",
        },
        status=MessageStatus.parsed,
        error_message=None,
        fast_path_completed_at=None,
        materialized_at=None,
    )
    service = IncidentMaterializationService(_SessionStub())  # type: ignore[arg-type]

    service.process_fast_path(
        representative,
        SimpleNamespace(decide_for_village=decide_for_village),
    )

    assert captured["candidate_text"] == "تحرك للدبابات باتجاه الخيام"
