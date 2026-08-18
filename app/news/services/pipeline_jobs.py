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
    ensure_pipeline_jobs_table(db)
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
