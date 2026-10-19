from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import engine
from app.news.services.pipeline.pipeline_jobs import (
    enqueue_pipeline_sweep,
    ensure_pipeline_jobs_table,
    reclaim_orphaned_pipeline_sweep_jobs,
)


@pytest.fixture
def db() -> Iterator[Session]:
    """Session whose every write, including the service-level commit() calls,
    lives in an outer transaction that is rolled back at teardown.

    The old version of these tests ran an unscoped ``DELETE FROM
    pipeline_sweep_jobs`` and committed it. Nothing here is ever committed
    for real, so rows the test did not create are never lost.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_enqueue_coalesces_pending_jobs(db: Session) -> None:
    ensure_pipeline_jobs_table(db)
    # Rolled back with the outer transaction; hides pre-existing rows from this test only.
    db.execute(text("DELETE FROM pipeline_sweep_jobs"))

    first = enqueue_pipeline_sweep(db, use_advisory_lock=False)
    second = enqueue_pipeline_sweep(db, use_advisory_lock=False)

    assert first == second
    pending = db.scalar(
        text("SELECT COUNT(*) FROM pipeline_sweep_jobs WHERE status = 'pending'")
    )
    assert pending == 1


def test_reclaim_orphaned_running_jobs(db: Session) -> None:
    ensure_pipeline_jobs_table(db)
    db.execute(text("DELETE FROM pipeline_sweep_jobs"))
    job_id = db.execute(
        text(
            """
            INSERT INTO pipeline_sweep_jobs (status, claimed_at)
            VALUES ('running', now())
            RETURNING id
            """
        )
    ).scalar_one()

    reclaimed = reclaim_orphaned_pipeline_sweep_jobs(db)

    assert reclaimed == 1
    status = db.scalar(
        text("SELECT status FROM pipeline_sweep_jobs WHERE id = :id"), {"id": job_id}
    )
    assert status == "pending"
