"""Phase 2: the pipeline must not overwrite or hide admin decisions."""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.news.models import IncidentDetail, MessageStatus
from app.news.repositories.incident_repository import IncidentRepository


def _sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


REJECTED_FILTER = "incidents.verification_status IS DISTINCT FROM 'rejected'"


# --- 2.4: candidate searches skip admin-rejected incidents -----------------

def test_duplicate_candidate_search_excludes_rejected() -> None:
    db = MagicMock()
    db.execute.return_value.all.return_value = []

    IncidentRepository(db).list_duplicate_candidates(
        village_id=1,
        event_date=date(2026, 9, 24),
        khabar_embedding=[0.1, 0.2],
        window_days=1,
    )

    assert REJECTED_FILTER in _sql(db.execute.call_args.args[0])


def test_fast_dedup_candidate_search_excludes_rejected() -> None:
    db = MagicMock()
    db.execute.return_value.all.return_value = []

    IncidentRepository(db).find_fast_dedup_candidates(
        village_id=1,
        condition_id=2,
        message_datetime=datetime(2026, 9, 24, tzinfo=timezone.utc),
        lookup_window_days=1,
    )

    assert REJECTED_FILTER in _sql(db.execute.call_args.args[0])


def test_story_candidate_search_excludes_rejected() -> None:
    db = MagicMock()
    db.execute.return_value.all.return_value = []

    IncidentRepository(db).find_story_candidates(
        village_ids={1},
        message_datetime=datetime(2026, 9, 24, tzinfo=timezone.utc),
        window_hours=24,
        embedding_threshold=0.5,
        max_results=5,
        candidate_embedding=[0.1, 0.2],
    )

    assert REJECTED_FILTER in _sql(db.execute.call_args.args[0])


def test_story_revision_demotes_verified_incident() -> None:
    db = MagicMock()
    db.scalar.return_value = None
    existing = SimpleNamespace(
        id=uuid4(),
        deaths=5,
        injuries=None,
        total_deaths=5,
        total_injuries=None,
        verification_status="verified",
        verification_reason=None,
    )
    repo = IncidentRepository(db)
    repo._story_revision_already_applied = MagicMock(return_value=False)
    repo._snapshot_merge_audit = MagicMock(return_value={})

    repo.apply_story_revision(existing, {"deaths": 6, "total_deaths": 6}, raw_message_id=42)

    assert existing.deaths == 6
    assert existing.verification_status == "needs_verification"
    assert "raw message 42" in existing.verification_reason


def test_demotion_leaves_non_verified_status_alone() -> None:
    incident = SimpleNamespace(verification_status="auto_processed", verification_reason=None)

    IncidentRepository._demote_verified_after_pipeline_write(incident, "reason")

    assert incident.verification_status == "auto_processed"


# --- 2.5: reject is per incident; merged duplicates cannot be "restored" ----

def _verification_fixture(*, other_live: bool):
    db = MagicMock()
    incident = SimpleNamespace(
        id=uuid4(),
        raw_message_id=7,
        verification_status="auto_processed",
        verification_reason=None,
        verified_by_user_id=None,
        verified_at=None,
    )
    raw_message = SimpleNamespace(
        status=MessageStatus.materialized,
        filter_result={"verdict": "accept"},
        error_message=None,
    )
    db.scalar.side_effect = [incident, raw_message, uuid4() if other_live else None]
    repo = IncidentRepository(db)
    repo.get_by_id = MagicMock(return_value="detail")
    return repo, incident, raw_message


def _update_status(repo, incident):
    return repo.set_verification(
        incident_id=incident.id,
        status="rejected",
        reason="not a war event",
        version=1,
        user_id=uuid4(),
    )


def test_rejecting_one_village_keeps_the_message_live_for_siblings() -> None:
    repo, incident, raw_message = _verification_fixture(other_live=True)

    _update_status(repo, incident)

    assert incident.verification_status == "rejected"
    assert raw_message.status == MessageStatus.materialized


def test_rejecting_the_last_live_village_rejects_the_message() -> None:
    repo, incident, raw_message = _verification_fixture(other_live=False)

    _update_status(repo, incident)

    assert raw_message.status == MessageStatus.rejected
    assert raw_message.filter_result["verdict"] == "reject"


def test_restore_of_merged_duplicate_is_blocked_with_canonical_id() -> None:
    from app.api import rejected_news_router as router

    canonical_id = uuid4()
    db = MagicMock()
    message = SimpleNamespace(status=MessageStatus.duplicate, raw_payload={})
    db.scalar.side_effect = [message, canonical_id]
    db.scalars.return_value.all.return_value = []

    with pytest.raises(HTTPException) as raised:
        router.restore_rejected_news(
            raw_message_id=9,
            current_user=SimpleNamespace(id=uuid4()),
            db=db,
        )

    assert raised.value.status_code == 409
    assert str(canonical_id) in raised.value.detail
    db.commit.assert_not_called()


# --- 2.7: partial multi-village failure is retried ---------------------------

def test_fast_path_claim_readmits_partial_failures() -> None:
    from app.news.repositories.pipeline_claim_repository import PipelineClaimRepository

    db = MagicMock()
    PipelineClaimRepository(db).claim_pending_fast_path()

    sql = _sql(db.scalar.call_args.args[0])
    assert "raw_messages.error_message LIKE 'fast_path: partial failure' || '%%'" in sql or (
        "fast_path: partial failure" in sql
    )


def test_partial_failure_marks_message_parsed_for_retry() -> None:
    from app.news.repositories.pipeline_claim_repository import PipelineClaimRepository

    db = MagicMock()
    message = SimpleNamespace(status=MessageStatus.materialized, error_message=None)
    db.get.return_value = message
    db.scalar.return_value = uuid4()

    marked = PipelineClaimRepository(db).mark_fast_path_partial_failure(
        7, RuntimeError("village 2 blew up")
    )

    assert marked is True
    assert message.status == MessageStatus.parsed
    assert message.error_message.startswith("fast_path: partial failure")


def test_failure_without_any_incident_is_not_marked_partial() -> None:
    from app.news.repositories.pipeline_claim_repository import PipelineClaimRepository

    db = MagicMock()
    message = SimpleNamespace(status=MessageStatus.parsed, error_message=None)
    db.get.return_value = message
    db.scalar.return_value = None

    assert PipelineClaimRepository(db).mark_fast_path_partial_failure(7, RuntimeError()) is False
    assert message.error_message is None


# --- 2.8: admin-cleared gates survive pipeline merges ------------------------

def test_admin_cleared_gate_is_not_reset_by_pipeline_merge() -> None:
    from app.news.services.incident_details.incident_detail_merge import (
        merge_incident_detail_fields,
    )

    detail = IncidentDetail(incident_id=uuid4())
    detail.la = False
    detail.admin_cleared_gates = ["la"]

    merge_incident_detail_fields(detail, {"la": True, "la_did": "D", "unifil": True})

    assert detail.la is False
    assert detail.la_did is None
    assert detail.unifil is True


def test_admin_edit_records_cleared_and_reenabled_gates() -> None:
    from app.news.services.incident_details.incident_detail_edit_service import (
        _record_admin_gate_provenance,
    )

    detail = IncidentDetail(incident_id=uuid4())
    _record_admin_gate_provenance(detail, {"la": False})
    assert detail.admin_cleared_gates == ["la"]

    _record_admin_gate_provenance(detail, {"la": True})
    assert detail.admin_cleared_gates is None


def test_pipeline_merge_clears_did_without_its_gate() -> None:
    from app.news.services.incident_details.incident_detail_merge import (
        merge_incident_detail_fields,
    )

    detail = IncidentDetail(incident_id=uuid4())

    merge_incident_detail_fields(detail, {"la_did": "D"})

    assert detail.la_did is None


# --- 2.10: merged-in categories get their own Tier 2 fill --------------------

def test_merge_sources_skip_own_message_and_already_filled(monkeypatch) -> None:
    from app.llm.dtos import ExtractionCategoryKey, ExtractionResult
    from app.news.services.extraction import merge_detail_fill as fill

    extraction = ExtractionResult(
        is_relevant=True,
        presence_category_keys=[ExtractionCategoryKey.lebanese_army],
        extraction_tier=2,
        model="test",
        extracted_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
    ).model_dump(mode="json")
    db = MagicMock()
    # merged_from ids (own=1, filled=2, new=3), then already-filled markers.
    db.scalars.side_effect = [
        MagicMock(all=MagicMock(return_value=["1", "2", "3"])),
        MagicMock(all=MagicMock(return_value=["2"])),
    ]
    db.get.return_value = SimpleNamespace(raw_text="خبر", extraction_result=extraction)
    incident = SimpleNamespace(id=uuid4(), raw_message_id=1)

    sources = fill.pending_merge_sources(db, incident)

    assert [source.raw_message_id for source in sources] == [3]


def test_manual_incident_merge_fill_runs_and_clears_pending(monkeypatch) -> None:
    from app.llm.dtos import ExtractionCategoryKey, ExtractionResult
    from app.news.services.extraction import merge_detail_fill as fill

    incident = SimpleNamespace(id=uuid4(), raw_message_id=None, is_deleted=False, details_pending=True)
    extraction = ExtractionResult(
        is_relevant=True,
        presence_category_keys=[ExtractionCategoryKey.lebanese_army],
        extraction_tier=2,
        model="test",
        extracted_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )
    source = fill.MergeSource(raw_message_id=3, post_text="خبر", extraction=extraction)
    session = MagicMock()
    session.__enter__.return_value = session
    session.get.return_value = incident
    monkeypatch.setattr(fill, "SessionLocal", lambda: session)
    monkeypatch.setattr(fill, "pending_merge_sources", lambda db, inc: [source])
    applied = []
    monkeypatch.setattr(
        fill,
        "apply_merge_source_categories",
        lambda db, inc, src, categories, **_: applied.append((src.raw_message_id, categories)),
    )
    classifier = MagicMock()
    classifier.extract_tier2_details.return_value = {"la": "category"}

    assert fill.run_merge_detail_fill_for_incident(incident.id, classifier) == 1

    assert applied == [(3, {"la": "category"})]
    assert incident.details_pending is False
