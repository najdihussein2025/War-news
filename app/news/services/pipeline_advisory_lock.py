from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

PIPELINE_SWEEP_ADVISORY_LOCK_KEY = 84729103
PIPELINE_WORKER_APPLICATION_NAME = "war-news-pipeline"


@dataclass(frozen=True)
class AdvisoryLockHolder:
    pid: int
    application_name: str | None
    state: str | None
    wait_event_type: str | None
    query: str | None


def list_pipeline_advisory_lock_holders(db: Session) -> list[AdvisoryLockHolder]:
    rows = db.execute(
        text(
            """
            SELECT
                psa.pid,
                psa.application_name,
                psa.state,
                psa.wait_event_type,
                psa.query
            FROM pg_locks pl
            JOIN pg_stat_activity psa ON psa.pid = pl.pid
            WHERE pl.locktype = 'advisory'
              AND pl.classid = 0
              AND pl.objid = :lock_key
              AND psa.pid <> pg_backend_pid()
            """
        ),
        {"lock_key": PIPELINE_SWEEP_ADVISORY_LOCK_KEY},
    ).mappings()
    return [
        AdvisoryLockHolder(
            pid=int(row["pid"]),
            application_name=row["application_name"],
            state=row["state"],
            wait_event_type=row["wait_event_type"],
            query=row["query"],
        )
        for row in rows
    ]


def is_stale_pipeline_lock_holder(
    holder: AdvisoryLockHolder,
    *,
    worker_application_name: str = PIPELINE_WORKER_APPLICATION_NAME,
    reclaim_other_workers: bool = False,
) -> bool:
    """
    A holder is stale when it cannot be a live dedicated pipeline-worker sweep.

    Backend --reload leftovers always qualify. Another pipeline-worker pid is
    only treated as stale when this process is the singleton worker starting up
    (``reclaim_other_workers=True``).
    """
    app_name = (holder.application_name or "").strip()
    if app_name != worker_application_name:
        return True
    return reclaim_other_workers


def reclaim_stale_pipeline_advisory_locks(
    db: Session,
    *,
    worker_application_name: str = PIPELINE_WORKER_APPLICATION_NAME,
    reclaim_other_workers: bool = False,
) -> int:
    holders = list_pipeline_advisory_lock_holders(db)
    if not holders:
        return 0

    terminated = 0
    for holder in holders:
        stale = is_stale_pipeline_lock_holder(
            holder,
            worker_application_name=worker_application_name,
            reclaim_other_workers=reclaim_other_workers,
        )
        logger.warning(
            "Pipeline advisory lock %s held by pid=%s application_name=%r "
            "state=%s wait_event_type=%s stale=%s query=%r",
            PIPELINE_SWEEP_ADVISORY_LOCK_KEY,
            holder.pid,
            holder.application_name,
            holder.state,
            holder.wait_event_type,
            stale,
            (holder.query or "")[:120],
        )
        if not stale:
            continue
        killed = bool(
            db.execute(
                text("SELECT pg_terminate_backend(:pid)"),
                {"pid": holder.pid},
            ).scalar_one()
        )
        if killed:
            terminated += 1
            logger.warning(
                "Terminated stale advisory-lock backend pid=%s application_name=%r",
                holder.pid,
                holder.application_name,
            )
    db.commit()
    return terminated
