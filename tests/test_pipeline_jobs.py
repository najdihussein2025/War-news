from sqlalchemy import text

from app.core.database import SessionLocal
from app.news.services.pipeline_jobs import (
    enqueue_pipeline_sweep,
    ensure_pipeline_jobs_table,
    reclaim_orphaned_pipeline_sweep_jobs,
)


def test_enqueue_coalesces_pending_jobs() -> None:
    with SessionLocal() as db:
        ensure_pipeline_jobs_table(db)
        db.execute(text("DELETE FROM pipeline_sweep_jobs"))
        db.commit()

        first = enqueue_pipeline_sweep(db, use_advisory_lock=False)
        second = enqueue_pipeline_sweep(db, use_advisory_lock=False)

        assert first == second
        pending = db.scalar(
            text("SELECT COUNT(*) FROM pipeline_sweep_jobs WHERE status = 'pending'")
        )
        assert pending == 1


def test_reclaim_orphaned_running_jobs() -> None:
    with SessionLocal() as db:
        ensure_pipeline_jobs_table(db)
        db.execute(text("DELETE FROM pipeline_sweep_jobs"))
        db.execute(
            text(
                """
                INSERT INTO pipeline_sweep_jobs (status, claimed_at)
                VALUES ('running', now())
                """
            )
        )
        db.commit()

        reclaimed = reclaim_orphaned_pipeline_sweep_jobs(db)

        assert reclaimed == 1
        status = db.scalar(
            text("SELECT status FROM pipeline_sweep_jobs ORDER BY id DESC LIMIT 1")
        )
        assert status == "pending"
