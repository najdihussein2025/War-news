"""4.4: relevance batches are leased so a concurrent sweep cannot re-classify them."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from app.news.repositories.raw_message_repository import RawMessageRepository


def test_relevance_batch_is_leased_and_committed_before_the_llm_call() -> None:
    db = MagicMock()
    rows = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    db.scalars.return_value.all.return_value = rows

    batch = RawMessageRepository(db).get_pending_unfiltered_batch(limit=15)

    assert batch == rows
    assert all(row.processing_claim_stage == "relevance_filter" for row in batch)
    assert all(row.processing_claimed_at is not None for row in batch)
    db.commit.assert_called_once()


def test_leased_rows_are_excluded_from_a_concurrent_sweep() -> None:
    db = MagicMock()
    db.scalars.return_value.all.return_value = []

    RawMessageRepository(db).get_pending_unfiltered_batch(limit=15)

    sql = str(
        db.scalars.call_args.args[0].compile(dialect=postgresql.dialect())
    )
    assert "raw_messages.processing_claimed_at IS NULL" in sql
    assert "raw_messages.processing_claimed_at <" in sql


def test_empty_batch_does_not_commit() -> None:
    db = MagicMock()
    db.scalars.return_value.all.return_value = []

    RawMessageRepository(db).get_pending_unfiltered_batch(limit=15)

    db.commit.assert_not_called()
