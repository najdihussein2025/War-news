from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.news.dtos.pipeline_dto import PipelineSweepResult, StageSweepResult
from app.news.services.pipeline_sweep_stages import (
    sweep_clustering,
    sweep_embedding_generation,
    sweep_extraction,
    sweep_matching,
    sweep_materialization,
    sweep_pre_extraction_dedup,
    sweep_relevance_filter,
)

logger = logging.getLogger(__name__)

# Fixed PostgreSQL advisory lock key for the CNRS post-webhook pipeline sweep.
# Must remain stable across deploys so concurrent webhook bursts serialize on one sweep.
PIPELINE_SWEEP_ADVISORY_LOCK_KEY = 84729103


def _try_acquire_pipeline_lock(db: Session) -> bool:
    return bool(
        db.execute(
            text("SELECT pg_try_advisory_lock(:lock_key)"),
            {"lock_key": PIPELINE_SWEEP_ADVISORY_LOCK_KEY},
        ).scalar_one()
    )


def _release_pipeline_lock(db: Session) -> None:
    db.execute(
        text("SELECT pg_advisory_unlock(:lock_key)"),
        {"lock_key": PIPELINE_SWEEP_ADVISORY_LOCK_KEY},
    )


def _log_stage_result(result: StageSweepResult) -> None:
    logger.info(
        "Pipeline stage=%s processed=%s succeeded=%s failed=%s elapsed_seconds=%.2f",
        result.stage,
        result.processed,
        result.succeeded,
        result.failed,
        result.elapsed_seconds,
    )


async def run_full_pipeline_sweep(
    *,
    max_rows: int | None = None,
    on_stage: Callable[[StageSweepResult], None] | None = None,
) -> PipelineSweepResult:
    """
    Run all pipeline stages in order, each sweeping every currently-eligible row.
    Per-stage, per-item failures do not abort the sweep.

    When max_rows is set, each stage processes at most that many eligible rows.
    """
    logger.info("Pipeline sweep triggered max_rows=%s", max_rows)
    sweep_started_at = time.monotonic()
    db = SessionLocal()
    stages: list[StageSweepResult] = []

    def _record_stage(result: StageSweepResult) -> None:
        stages.append(result)
        _log_stage_result(result)
        if on_stage is not None:
            on_stage(result)

    try:
        try:
            if not _try_acquire_pipeline_lock(db):
                elapsed_seconds = time.monotonic() - sweep_started_at
                logger.info(
                    "Pipeline sweep skipped: advisory lock %s already held elapsed_seconds=%.2f",
                    PIPELINE_SWEEP_ADVISORY_LOCK_KEY,
                    elapsed_seconds,
                )
                return PipelineSweepResult(
                    skipped=True,
                    skip_reason="pipeline_sweep_already_running",
                    stages=[],
                    elapsed_seconds=elapsed_seconds,
                )

            if max_rows is not None:
                logger.info("Pipeline sweep starting with max_rows=%s per stage", max_rows)

            try:
                _record_stage(await sweep_relevance_filter(db, max_rows=max_rows))
                _record_stage(sweep_pre_extraction_dedup(db, max_rows=max_rows))
                _record_stage(sweep_extraction(db, max_rows=max_rows))
                _record_stage(sweep_matching(db, max_rows=max_rows))
                _record_stage(sweep_embedding_generation(db, max_rows=max_rows))
                _record_stage(sweep_clustering(db, max_rows=max_rows))
                _record_stage(sweep_materialization(db, max_rows=max_rows))
            finally:
                _release_pipeline_lock(db)

            elapsed_seconds = time.monotonic() - sweep_started_at
            logger.info(
                "Pipeline sweep completed elapsed_seconds=%.2f stages=%s",
                elapsed_seconds,
                ", ".join(
                    f"{stage.stage}(processed={stage.processed},succeeded={stage.succeeded},"
                    f"failed={stage.failed},elapsed={stage.elapsed_seconds:.2f}s)"
                    for stage in stages
                ),
            )
            return PipelineSweepResult(
                skipped=False,
                stages=stages,
                elapsed_seconds=elapsed_seconds,
            )
        except Exception:
            logger.exception(
                "Pipeline sweep failed elapsed_seconds=%.2f",
                time.monotonic() - sweep_started_at,
            )
            raise
    finally:
        db.close()


def run_full_pipeline_sweep_sync(*, max_rows: int | None = None) -> None:
    """Run the sweep in a worker thread (BackgroundTasks dispatches sync callables off-loop)."""
    asyncio.run(run_full_pipeline_sweep(max_rows=max_rows))
