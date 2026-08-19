from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

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


def _format_exception(exc: BaseException) -> str:
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return f"{type(exc).__name__} (no message)"


def _log_stage_result(result: StageSweepResult) -> None:
    logger.info(
        "Pipeline stage=%s processed=%s succeeded=%s failed=%s elapsed_seconds=%.2f",
        result.stage,
        result.processed,
        result.succeeded,
        result.failed,
        result.elapsed_seconds,
    )


async def _run_isolated_stage(
    *,
    stage_name: str,
    runner: Callable[[], Awaitable[StageSweepResult] | StageSweepResult],
    record: Callable[[StageSweepResult], None],
) -> None:
    """Run one stage; log and record failures without aborting later stages."""
    started_at = time.monotonic()
    try:
        result = runner()
        if asyncio.iscoroutine(result):
            result = await result
        record(result)
        if result.failed > 0:
            logger.warning(
                "Pipeline stage=%s completed with item failures processed=%s "
                "succeeded=%s failed=%s",
                result.stage,
                result.processed,
                result.succeeded,
                result.failed,
            )
    except Exception as exc:
        logger.exception(
            "Pipeline stage=%s failed; continuing remaining stages error=%s",
            stage_name,
            _format_exception(exc),
        )
        record(
            StageSweepResult(
                stage=stage_name,
                processed=0,
                succeeded=0,
                failed=1,
                elapsed_seconds=time.monotonic() - started_at,
            )
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
                await _run_isolated_stage(
                    stage_name="relevance_filter",
                    runner=lambda: sweep_relevance_filter(
                        sweep_db, max_rows=max_rows
                    ),
                    record=_record_stage,
                )
            finally:
                sweep_db.close()

            await _run_isolated_stage(
                stage_name="pre_extraction_dedup",
                runner=lambda: sweep_pre_dedup_concurrent(max_rows=max_rows),
                record=_record_stage,
            )
            await _run_isolated_stage(
                stage_name="tier1_extraction",
                runner=lambda: sweep_extraction_concurrent(max_rows=max_rows),
                record=_record_stage,
            )
            await _run_isolated_stage(
                stage_name="matching",
                runner=lambda: sweep_matching_concurrent(max_rows=max_rows),
                record=_record_stage,
            )
            await _run_isolated_stage(
                stage_name="fast_path",
                runner=lambda: sweep_fast_path_concurrent(max_rows=max_rows),
                record=_record_stage,
            )
            await _run_isolated_stage(
                stage_name="tier2_detail_fill",
                runner=lambda: sweep_tier2_detail_fill_concurrent(max_rows=max_rows),
                record=_record_stage,
            )

            for stage_name, sweep_fn in (
                ("embedding", sweep_embedding_generation),
                ("clustering", sweep_clustering),
                ("materialization", sweep_materialization),
            ):
                post_db = SessionLocal()
                try:
                    await _run_isolated_stage(
                        stage_name=stage_name,
                        runner=lambda sweep_fn=sweep_fn, post_db=post_db: sweep_fn(
                            post_db, max_rows=max_rows
                        ),
                        record=_record_stage,
                    )
                finally:
                    post_db.close()
        finally:
            if lock_db is not None:
                _release_pipeline_lock(lock_db)

        elapsed_seconds = time.monotonic() - sweep_started_at
        failed_stages = [stage.stage for stage in stages if stage.failed > 0]
        stage_summary = ", ".join(
            f"{stage.stage}(processed={stage.processed},succeeded={stage.succeeded},"
            f"failed={stage.failed},elapsed={stage.elapsed_seconds:.2f}s)"
            for stage in stages
        )
        if failed_stages:
            logger.warning(
                "Pipeline sweep completed with stage failures elapsed_seconds=%.2f "
                "failed_stages=%s stages=%s",
                elapsed_seconds,
                ",".join(failed_stages),
                stage_summary,
            )
        else:
            logger.info(
                "Pipeline sweep completed elapsed_seconds=%.2f stages=%s",
                elapsed_seconds,
                stage_summary,
            )
        return PipelineSweepResult(
            skipped=False,
            stages=stages,
            elapsed_seconds=elapsed_seconds,
            partial_failure=bool(failed_stages),
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
