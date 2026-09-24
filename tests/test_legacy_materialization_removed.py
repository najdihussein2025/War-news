from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.news.models import MessageStatus
from app.news.services.materialization.incident_materialization_service import (
    AMBIGUOUS_SUB_EVENT_SCOPE_REVIEW_REASON,
    IncidentMaterializationService,
)


def test_ambiguous_scope_hold_is_terminal_status() -> None:
    service = object.__new__(IncidentMaterializationService)
    service.db = MagicMock()
    representative = SimpleNamespace(
        id=7,
        status=MessageStatus.parsed,
        filter_result={"verdict": "accept"},
        low_confidence_relevance=False,
        fast_path_completed_at=None,
        error_message=None,
    )

    service._mark_raw_message_needs_review(
        representative,
        AMBIGUOUS_SUB_EVENT_SCOPE_REVIEW_REASON,
    )

    # status=parsed is what every materialization claim selects on; the hold
    # must leave it so no stage can materialize the message automatically.
    assert representative.status == MessageStatus.held_for_review
    assert representative.filter_result["needs_review"] is True


def test_automatic_sweeps_do_not_run_legacy_materialization() -> None:
    import scripts.live_sweep_new_only as live_sweep
    from app.news.services.pipeline import pipeline_orchestrator

    assert not hasattr(pipeline_orchestrator, "sweep_materialization")
    assert not hasattr(live_sweep, "sweep_materialization")


def test_duplicate_match_reconciliation_stage_keeps_side_effect(monkeypatch) -> None:
    from app.news.services.pipeline import pipeline_sweep_stages as stages

    monkeypatch.setattr(
        stages, "reconcile_orphaned_soft_deleted_incidents", lambda db: 3
    )

    result = stages.sweep_duplicate_match_reconciliation(MagicMock())

    assert result.stage == "duplicate_match_reconciliation"
    assert result.succeeded == 3
