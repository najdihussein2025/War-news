from __future__ import annotations

import logging
import time

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging_config import configure_logging
from app.news.services.pipeline_advisory_lock import (
    PIPELINE_WORKER_APPLICATION_NAME,
    reclaim_stale_pipeline_advisory_locks,
)
from app.news.services.pipeline_jobs import (
    claim_next_pipeline_sweep_job,
    finish_pipeline_sweep_job,
)
from app.news.services.pipeline_orchestrator import run_full_pipeline_sweep_sync

logger = logging.getLogger(__name__)


def _reclaim_stale_locks() -> None:
    with SessionLocal() as db:
        terminated = reclaim_stale_pipeline_advisory_locks(
            db,
            worker_application_name=PIPELINE_WORKER_APPLICATION_NAME,
            reclaim_other_workers=True,
        )
        if terminated:
            logger.warning(
                "Reclaimed %s stale pipeline advisory lock connection(s) on worker start",
                terminated,
            )


def run_worker_forever() -> None:
    configure_logging()
    logger.info(
        "Pipeline worker starting application_name=%s poll_seconds=%s",
        settings.pg_application_name,
        settings.pipeline_worker_poll_seconds,
    )
    _reclaim_stale_locks()

    while True:
        with SessionLocal() as db:
            job = claim_next_pipeline_sweep_job(db)
        if job is None:
            time.sleep(settings.pipeline_worker_poll_seconds)
            continue

        job_id = int(job["id"])
        max_rows = job["max_rows"]
        use_advisory_lock = bool(job["use_advisory_lock"])
        logger.info(
            "Pipeline worker claimed job_id=%s max_rows=%s use_advisory_lock=%s",
            job_id,
            max_rows,
            use_advisory_lock,
        )
        status = "succeeded"
        try:
            run_full_pipeline_sweep_sync(
                max_rows=int(max_rows) if max_rows is not None else None,
                use_advisory_lock=use_advisory_lock,
            )
        except Exception:
            status = "failed"
            logger.exception("Pipeline worker job_id=%s failed", job_id)
        with SessionLocal() as db:
            finish_pipeline_sweep_job(db, job_id, status=status)


if __name__ == "__main__":
    run_worker_forever()
