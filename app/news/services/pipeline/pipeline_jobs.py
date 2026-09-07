from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_ENSURE_JOBS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS pipeline_sweep_jobs (
    id BIGSERIAL PRIMARY KEY,
    max_rows INTEGER NULL,
    use_advisory_lock BOOLEAN NOT NULL DEFAULT TRUE,
    status TEXT NOT NULL DEFAULT 'pending',
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL
)
"""


def ensure_pipeline_jobs_table(db: Session) -> None:
    db.execute(text(_ENSURE_JOBS_TABLE_SQL))
    db.commit()


def enqueue_pipeline_sweep(
    db: Session,
    *,
    max_rows: int | None = None,
    use_advisory_lock: bool = True,
) -> int:
    """Queue a pipeline drain. Coalesces with an existing pending/running job."""
    ensure_pipeline_jobs_table(db)
    existing_job_id = db.execute(
        text(
            """
            SELECT id
            FROM pipeline_sweep_jobs
            WHERE status IN ('pending', 'running')
            ORDER BY id ASC
            LIMIT 1
            """
        )
    ).scalar_one_or_none()
    if existing_job_id is not None:
        logger.info(
            "Pipeline sweep already queued job_id=%s; skipping duplicate enqueue",
            existing_job_id,
        )
        db.commit()
        return int(existing_job_id)

    job_id = db.execute(
        text(
            """
            INSERT INTO pipeline_sweep_jobs (max_rows, use_advisory_lock, status)
            VALUES (:max_rows, :use_advisory_lock, 'pending')
            RETURNING id
            """
        ),
        {"max_rows": max_rows, "use_advisory_lock": use_advisory_lock},
    ).scalar_one()
    db.commit()
    logger.info(
        "Enqueued pipeline sweep job_id=%s max_rows=%s use_advisory_lock=%s",
        job_id,
        max_rows,
        use_advisory_lock,
    )
    return int(job_id)


def reclaim_orphaned_pipeline_sweep_jobs(db: Session) -> int:
    """Reset all running jobs to pending. Call only at worker startup."""
    ensure_pipeline_jobs_table(db)
    reclaimed_ids = db.execute(
        text(
            """
            UPDATE pipeline_sweep_jobs
            SET status = 'pending', claimed_at = NULL
            WHERE status = 'running'
            RETURNING id
            """
        )
    ).scalars().all()
    db.commit()
    if reclaimed_ids:
        logger.warning(
            "Reclaimed orphaned pipeline sweep jobs count=%s job_ids=%s",
            len(reclaimed_ids),
            list(reclaimed_ids),
        )
    return len(reclaimed_ids)


def reclaim_stale_pipeline_sweep_jobs(
    db: Session,
    *,
    max_age_minutes: int = 60,
) -> int:
    """Reset running jobs whose worker died mid-drain back to pending."""
    ensure_pipeline_jobs_table(db)
    reclaimed_ids = db.execute(
        text(
            """
            UPDATE pipeline_sweep_jobs
            SET status = 'pending', claimed_at = NULL
            WHERE status = 'running'
              AND claimed_at IS NOT NULL
              AND claimed_at < now() - make_interval(mins => :max_age_minutes)
            RETURNING id
            """
        ),
        {"max_age_minutes": max_age_minutes},
    ).scalars().all()
    db.commit()
    if reclaimed_ids:
        logger.warning(
            "Reclaimed stale pipeline sweep jobs count=%s job_ids=%s",
            len(reclaimed_ids),
            list(reclaimed_ids),
        )
    return len(reclaimed_ids)


def claim_next_pipeline_sweep_job(db: Session) -> dict[str, object] | None:
    ensure_pipeline_jobs_table(db)
    row = db.execute(
        text(
            """
            SELECT id, max_rows, use_advisory_lock
            FROM pipeline_sweep_jobs
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        )
    ).mappings().first()
    if row is None:
        db.commit()
        return None

    db.execute(
        text(
            """
            UPDATE pipeline_sweep_jobs
            SET status = 'running', claimed_at = now()
            WHERE id = :job_id
            """
        ),
        {"job_id": row["id"]},
    )
    db.commit()
    return {
        "id": int(row["id"]),
        "max_rows": row["max_rows"],
        "use_advisory_lock": bool(row["use_advisory_lock"]),
    }


def finish_pipeline_sweep_job(db: Session, job_id: int, *, status: str) -> None:
    db.execute(
        text(
            """
            UPDATE pipeline_sweep_jobs
            SET status = :status, finished_at = now()
            WHERE id = :job_id
            """
        ),
        {"status": status, "job_id": job_id},
    )
    db.commit()
