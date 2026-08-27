from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.news.models import MessageStatus, RawMessage
from app.news.repositories.pipeline_claim_repository import PipelineClaimRepository


def test_claim_pending_extraction_query_uses_skip_locked() -> None:
    stmt = (
        select(RawMessage)
        .where(
            RawMessage.status == MessageStatus.parsed,
            RawMessage.extraction_result.is_(None),
            RawMessage.duplicate_of_id.is_(None),
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    compiled = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "SKIP LOCKED" in compiled.upper()


def test_claim_pending_extraction_marks_processing_lease() -> None:
    now = datetime.now(timezone.utc)
    message = RawMessage(
        source_id=1,
        raw_payload={},
        status=MessageStatus.parsed,
        processing_claim_stage=None,
        processing_claimed_at=now - timedelta(minutes=10),
        processing_claimed_by=None,
    )

    class _DBStub:
        def __init__(self, value: RawMessage) -> None:
            self.value = value
            self.added: list[object] = []

        def scalar(self, _statement):
            return self.value

        def add(self, value: object) -> None:
            self.added.append(value)

    db = _DBStub(message)
    claimed = PipelineClaimRepository(db).claim_pending_extraction()  # type: ignore[arg-type]

    assert claimed is message
    assert claimed.processing_claim_stage == "tier1_extraction"
    assert claimed.processing_claimed_at is not None
    assert claimed.processing_claimed_by
    assert db.added == [message]


def test_claim_pending_match_excludes_fresh_processing_leases() -> None:
    repo = PipelineClaimRepository(db=None)  # type: ignore[arg-type]
    stmt = repo._claimable_raw_messages().where(  # type: ignore[attr-defined]
        RawMessage.status == MessageStatus.parsed,
        RawMessage.extraction_result.is_not(None),
        RawMessage.match_result.is_(None),
        RawMessage.duplicate_of_id.is_(None),
    )
    compiled = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "processing_claimed_at" in compiled
    assert "processing_claim_stage" in compiled


def test_claim_pending_fast_path_excludes_rows_with_active_incidents() -> None:
    repo = PipelineClaimRepository(db=None)  # type: ignore[arg-type]
    assert hasattr(repo, "claim_pending_fast_path")
    assert hasattr(repo, "terminalize_ineligible_fast_path")


def test_claim_pending_fast_path_query_requires_materializable_match() -> None:
    stmt = (
        select(RawMessage)
        .where(
            RawMessage.status == MessageStatus.parsed,
            RawMessage.duplicate_of_id.is_(None),
            RawMessage.match_result.is_not(None),
            RawMessage.extraction_result.is_not(None),
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    compiled = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "SKIP LOCKED" in compiled.upper()
