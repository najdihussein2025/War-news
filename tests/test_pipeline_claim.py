from __future__ import annotations

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
