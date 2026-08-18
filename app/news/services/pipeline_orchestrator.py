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
from app.news.services.pipeline_advisory_lock import PIPELINE_SWEEP_ADVISORY_LOCK_KEY
from app.news.services.pipeline_concurrent_sweeps import (
    sweep_extraction_concurrent,
    sweep_fast_path_concurrent,
    sweep_matching_concurrent,
    sweep_pre_dedup_concurrent,
    sweep_tier2_detail_fill_concurrent,
)
from app.news.services.pipeline_sweep_stages import (
    sweep_clustering,
    sweep_embedding_generation,
    sweep_materialization,
    sweep_relevance_filter,
)

logger = logging.getLogger(__name__)

# Advisory lock for manual/ops-triggered sweeps only (CLI and dedicated worker).


def _try_acquire_pipeline_lock(db: Session) -> bool:
    acquired = bool(
        db.execute(
            text("SELECT pg_try_advisory_lock(:lock_key)"),
            {"lock_key": PIPELINE_SWEEP_ADVISORY_LOCK_KEY},
        ).scalar_one()
    )
    if acquired:
        # Session-level advisory locks survive commit; end the idle transaction
        # so this connection does not permanently occupy a pool slot.
        db.commit()
    return acquired


def _release_pipeline_lock(db: Session) -> None:
    db.execute(
        text("SELECT pg_advisory_unlock(:lock_key)"),
        {"lock_key": PIPELINE_SWEEP_ADVISORY_LOCK_KEY},
    )
    db.commit()


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
    use_advisory_lock: bool = False,
    on_stage: Callable[[StageSweepResult], None] | None = None,
) -> PipelineSweepResult:
    """
    Run all pipeline stages in order, each sweeping every currently-eligible row.
    Per-stage, per-item failures do not abort the sweep.

    Webhook triggers use ``use_advisory_lock=False`` and concurrent workers with
    row-level ``SELECT ... FOR UPDATE SKIP LOCKED`` claiming. Manual CLI/admin
    sweeps pass ``use_advisory_lock=True`` to serialize against other manual runs.
    """
    logger.info(
        "Pipeline sweep triggered max_rows=%s use_advisory_lock=%s",
        max_rows,
        use_advisory_lock,
    )
    sweep_started_at = time.monotonic()
    stages: list[StageSweepResult] = []
    lock_db: Session | None = None

    def _record_stage(result: StageSweepResult) -> None:
        stages.append(result)
        _log_stage_result(result)
        if on_stage is not None:
            on_stage(result)

    try:
        if use_advisory_lock:
            lock_db = SessionLocal()
            if not _try_acquire_pipeline_lock(lock_db):
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
            sweep_db = SessionLocal()
            try:
                _record_stage(
                    await sweep_relevance_filter(sweep_db, max_rows=max_rows)
                )
            finally:
                sweep_db.close()

            _record_stage(await sweep_pre_dedup_concurrent(max_rows=max_rows))
            _record_stage(await sweep_extraction_concurrent(max_rows=max_rows))
            _record_stage(await sweep_matching_concurrent(max_rows=max_rows))
            _record_stage(await sweep_fast_path_concurrent(max_rows=max_rows))
            _record_stage(await sweep_tier2_detail_fill_concurrent(max_rows=max_rows))

            post_db = SessionLocal()
            try:
                _record_stage(
                    sweep_embedding_generation(post_db, max_rows=max_rows)
                )
                _record_stage(sweep_clustering(post_db, max_rows=max_rows))
                _record_stage(sweep_materialization(post_db, max_rows=max_rows))
            finally:
                post_db.close()
        finally:
            if lock_db is not None:
                _release_pipeline_lock(lock_db)

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
        if lock_db is not None:
            lock_db.close()


def run_full_pipeline_sweep_sync(
    *,
    max_rows: int | None = None,
    use_advisory_lock: bool = False,
) -> None:
    """Run the sweep synchronously. Used by the dedicated pipeline-worker process."""
    asyncio.run(
        run_full_pipeline_sweep(
            max_rows=max_rows,
            use_advisory_lock=use_advisory_lock,
        )
    )
