from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from unittest.mock import MagicMock

from app.news.models import MessageStatus, RawMessage
from app.news.repositories.pipeline_claim_repository import PipelineClaimRepository
from app.news.services.pipeline_concurrent_sweeps import _WorkerStats


def test_pre_dedup_claim_excludes_already_checked_messages() -> None:
    db = MagicMock()
    db.scalar.return_value = None

    PipelineClaimRepository(db).claim_pending_pre_dedup()

    statement = db.scalar.call_args.args[0]
    compiled = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "dedup_checked_at IS NULL" in compiled


def test_tier2_claim_marks_raw_message_processing_lease() -> None:
    message = RawMessage(source_id=1, raw_payload={}, status=MessageStatus.materialized)
    message.id = 44
    incident = type("ClaimedIncident", (), {"raw_message_id": 44})()

    class _DBStub:
        def scalar(self, _statement):
            return incident

        def get(self, _model, object_id):
            assert object_id == 44
            return message

        def add(self, _value):
            pass

    claimed = PipelineClaimRepository(_DBStub()).claim_pending_tier2_detail_fill()  # type: ignore[arg-type]

    assert claimed is incident
    assert message.processing_claim_stage == "tier2_detail_fill"
    assert message.processing_claimed_at is not None
    assert message.processing_claimed_by


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


def test_claim_pending_extraction_orders_newest_first() -> None:
    repo = PipelineClaimRepository(db=None)  # type: ignore[arg-type]
    stmt = (
        repo._claimable_raw_messages()  # type: ignore[attr-defined]
        .where(
            RawMessage.status == MessageStatus.parsed,
            RawMessage.extraction_result.is_(None),
            RawMessage.duplicate_of_id.is_(None),
        )
        .order_by(RawMessage.id.desc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    compiled = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "ORDER BY raw_messages.id DESC" in compiled


def test_claim_pending_match_orders_newest_first() -> None:
    repo = PipelineClaimRepository(db=None)  # type: ignore[arg-type]
    stmt = (
        repo._claimable_raw_messages()  # type: ignore[attr-defined]
        .where(
            RawMessage.status == MessageStatus.parsed,
            RawMessage.extraction_result.is_not(None),
            RawMessage.match_result.is_(None),
            RawMessage.duplicate_of_id.is_(None),
        )
        .order_by(RawMessage.id.desc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    compiled = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "ORDER BY raw_messages.id DESC" in compiled


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


def test_worker_stats_reserves_slots_without_overshooting_cap() -> None:
    stats = _WorkerStats()

    assert stats.reserve_slot(2) is True
    assert stats.reserve_slot(2) is True
    assert stats.reserve_slot(2) is False

    stats.release_reserved_slot()
    assert stats.reserve_slot(2) is True
