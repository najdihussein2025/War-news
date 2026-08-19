from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.api.factories.action_factory import build_match_incident_action
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.ollama_concurrency import run_with_ollama_limit
from app.news.dtos.pipeline_dto import StageSweepResult
from app.news.models import RawMessage
from app.news.repositories.incident_repository import IncidentRepository
from app.news.repositories.pipeline_claim_repository import PipelineClaimRepository
from app.news.repositories.raw_message_repository import RawMessageRepository
from app.news.services.fast_path_dedup import FastPathDedupService
from app.news.services.incident_materialization_service import (
    IncidentMaterializationService,
)
from app.llm.services.transient_llm_errors import ExtractionRetryCappedError
from app.news.services.pipeline_llm_workers import (
    run_tier1_extraction_for_message,
    run_tier2_detail_fill_for_message,
)
from app.news.services.pre_extraction_dedup import process_pre_dedup_message

logger = logging.getLogger(__name__)


def _format_exception(exc: BaseException) -> str:
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return f"{type(exc).__name__} (no message)"


@dataclass
class _WorkerStats:
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    terminalized: int = 0
    capped: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record_success(self) -> None:
        with self.lock:
            self.processed += 1
            self.succeeded += 1

    def record_failure(self) -> None:
        with self.lock:
            self.processed += 1
            self.failed += 1

    def record_terminalized(self) -> None:
        with self.lock:
            self.processed += 1
            self.succeeded += 1
            self.terminalized += 1

    def record_capped(self) -> None:
        with self.lock:
            self.processed += 1
            self.failed += 1
            self.capped += 1

    def should_stop(self, max_rows: int | None) -> bool:
        if max_rows is None:
            return False
        with self.lock:
            return self.processed >= max_rows


def _worker_count() -> int:
    return max(1, settings.ollama_max_concurrent_requests)


def _claim_raw_message_id(claim_fn: Callable[[Session], RawMessage | None]) -> int | None:
    """Claim one row and commit immediately so the FOR UPDATE lock is released."""
    with SessionLocal() as db:
        message = claim_fn(db)
        if message is None:
            return None
        raw_message_id = message.id
        db.commit()
        return raw_message_id


def _claim_tier2_work() -> tuple[object, int] | None:
    """Claim one details_pending incident; return (incident_id, raw_message_id)."""
    with SessionLocal() as db:
        incident = PipelineClaimRepository(db).claim_pending_tier2_detail_fill()
        if incident is None:
            return None
        incident_id = incident.id
        raw_message_id = incident.raw_message_id
        db.commit()
        if raw_message_id is None:
            logger.error(
                "Concurrent tier2 detail fill claimed incident_id=%s with no raw_message_id",
                incident_id,
            )
            return None
        return incident_id, raw_message_id


def _effective_pre_dedup_max_rows(max_rows: int | None) -> int | None:
    if max_rows is not None:
        return max_rows
    return settings.pre_dedup_sweep_row_cap


async def _pre_dedup_worker(
    stats: _WorkerStats,
    *,
    max_rows: int | None,
) -> None:
    threshold = settings.pre_dedup_similarity_threshold
    while True:
        if stats.should_stop(max_rows):
            return

        raw_message_id = await asyncio.to_thread(
            _claim_raw_message_id,
            lambda db: PipelineClaimRepository(db).claim_pending_pre_dedup(),
        )
        if raw_message_id is None:
            return

        with SessionLocal() as db:
            try:
                process_pre_dedup_message(
                    db,
                    raw_message_id=raw_message_id,
                    threshold=threshold,
                )
                stats.record_success()
            except Exception:
                db.rollback()
                logger.exception(
                    "Concurrent pre_dedup failed raw_message_id=%s",
                    raw_message_id,
                )
                stats.record_failure()


async def sweep_pre_dedup_concurrent(
    *,
    max_rows: int | None = None,
) -> StageSweepResult:
    started_at = time.monotonic()
    stats = _WorkerStats()
    effective_max_rows = _effective_pre_dedup_max_rows(max_rows)
    workers = [
        asyncio.create_task(
            _pre_dedup_worker(stats, max_rows=effective_max_rows),
            name=f"pre-dedup-worker-{index}",
        )
        for index in range(_worker_count())
    ]
    await asyncio.gather(*workers)
    elapsed_seconds = time.monotonic() - started_at
    logger.info(
        "Concurrent pre_dedup completed cap=%s processed=%s succeeded=%s failed=%s",
        effective_max_rows,
        stats.processed,
        stats.succeeded,
        stats.failed,
    )
    return StageSweepResult(
        stage="pre_extraction_dedup",
        processed=stats.processed,
        succeeded=stats.succeeded,
        failed=stats.failed,
        elapsed_seconds=elapsed_seconds,
    )


async def _tier1_extraction_worker(
    stats: _WorkerStats,
    *,
    max_rows: int | None,
) -> None:
    while True:
        if stats.should_stop(max_rows):
            return

        raw_message_id = await asyncio.to_thread(
            _claim_raw_message_id,
            lambda db: PipelineClaimRepository(db).claim_pending_extraction(),
        )
        if raw_message_id is None:
            return

        try:
            await run_with_ollama_limit(
                run_tier1_extraction_for_message,
                raw_message_id,
            )
            stats.record_success()
        except ExtractionRetryCappedError as exc:
            logger.error(
                "Concurrent tier1 extraction capped raw_message_id=%s error=%s",
                raw_message_id,
                _format_exception(exc),
            )
            stats.record_capped()
        except Exception as exc:
            logger.exception(
                "Concurrent tier1 extraction failed raw_message_id=%s error=%s",
                raw_message_id,
                _format_exception(exc),
            )
            stats.record_failure()


async def sweep_extraction_concurrent(
    *,
    max_rows: int | None = None,
) -> StageSweepResult:
    reset_count = 0
    reset_capped = 0
    with SessionLocal() as db:
        reset_count, reset_capped = RawMessageRepository(
            db
        ).reset_retryable_extraction_errors()
        if reset_count or reset_capped:
            logger.info(
                "Extraction retry reset re_queued=%s capped=%s before tier1 sweep",
                reset_count,
                reset_capped,
            )

    started_at = time.monotonic()
    stats = _WorkerStats()
    workers = [
        asyncio.create_task(
            _tier1_extraction_worker(stats, max_rows=max_rows),
            name=f"tier1-extraction-worker-{index}",
        )
        for index in range(_worker_count())
    ]
    await asyncio.gather(*workers)
    elapsed_seconds = time.monotonic() - started_at
    capped_total = reset_capped + stats.capped
    logger.info(
        "Concurrent tier1 extraction completed processed=%s succeeded=%s "
        "failed=%s capped=%s",
        stats.processed,
        stats.succeeded,
        stats.failed - stats.capped,
        capped_total,
    )
    return StageSweepResult(
        stage="tier1_extraction",
        processed=stats.processed,
        succeeded=stats.succeeded,
        failed=stats.failed,
        elapsed_seconds=elapsed_seconds,
    )


async def _matching_worker(
    stats: _WorkerStats,
    *,
    max_rows: int | None,
) -> None:
    while True:
        if stats.should_stop(max_rows):
            return

        raw_message_id = await asyncio.to_thread(
            _claim_raw_message_id,
            lambda db: PipelineClaimRepository(db).claim_pending_match(),
        )
        if raw_message_id is None:
            return

        with SessionLocal() as db:
            action = build_match_incident_action(db)
            try:
                action.execute(raw_message_id)
                stats.record_success()
            except Exception:
                logger.exception(
                    "Concurrent matching failed raw_message_id=%s",
                    raw_message_id,
                )
                stats.record_failure()


async def sweep_matching_concurrent(
    *,
    max_rows: int | None = None,
) -> StageSweepResult:
    started_at = time.monotonic()
    stats = _WorkerStats()
    workers = [
        asyncio.create_task(
            _matching_worker(stats, max_rows=max_rows),
            name=f"matching-worker-{index}",
        )
        for index in range(_worker_count())
    ]
    await asyncio.gather(*workers)
    elapsed_seconds = time.monotonic() - started_at
    return StageSweepResult(
        stage="matching",
        processed=stats.processed,
        succeeded=stats.succeeded,
        failed=stats.failed,
        elapsed_seconds=elapsed_seconds,
    )


async def _fast_path_worker(
    stats: _WorkerStats,
    *,
    max_rows: int | None,
) -> None:
    while True:
        if stats.should_stop(max_rows):
            return

        raw_message_id = await asyncio.to_thread(
            _claim_raw_message_id,
            lambda db: PipelineClaimRepository(db).claim_pending_fast_path(),
        )
        if raw_message_id is None:
            return

        with SessionLocal() as db:
            message = db.get(RawMessage, raw_message_id)
            if message is None:
                continue

            incident_repo = IncidentRepository(db)
            service = IncidentMaterializationService(db)
            fast_dedup = FastPathDedupService(incident_repo)
            try:
                service.process_fast_path(message, fast_dedup)
                db.commit()
                if service.fast_stats.marked_unmaterializable:
                    stats.record_terminalized()
                else:
                    stats.record_success()
            except Exception as exc:
                db.rollback()
                logger.exception(
                    "Concurrent fast_path failed raw_message_id=%s error=%s",
                    raw_message_id,
                    _format_exception(exc),
                )
                stats.record_failure()


async def sweep_fast_path_concurrent(
    *,
    max_rows: int | None = None,
) -> StageSweepResult:
    started_at = time.monotonic()

    def _terminalize() -> int:
        with SessionLocal() as db:
            return PipelineClaimRepository(db).terminalize_ineligible_fast_path()

    terminalized = await asyncio.to_thread(_terminalize)
    if terminalized:
        logger.info(
            "Fast path terminalized %s permanently unmaterializable raw_messages",
            terminalized,
        )

    stats = _WorkerStats()
    workers = [
        asyncio.create_task(
            _fast_path_worker(stats, max_rows=max_rows),
            name=f"fast-path-worker-{index}",
        )
        for index in range(_worker_count())
    ]
    await asyncio.gather(*workers)
    elapsed_seconds = time.monotonic() - started_at
    terminalized_total = terminalized + stats.terminalized
    logger.info(
        "Concurrent fast path completed processed=%s succeeded=%s failed=%s terminalized=%s",
        stats.processed + terminalized,
        stats.succeeded + terminalized,
        stats.failed,
        terminalized_total,
    )
    return StageSweepResult(
        stage="fast_path",
        processed=stats.processed + terminalized,
        succeeded=stats.succeeded + terminalized,
        failed=stats.failed,
        elapsed_seconds=elapsed_seconds,
    )


async def _tier2_detail_fill_worker(
    stats: _WorkerStats,
    *,
    max_rows: int | None,
) -> None:
    while True:
        if stats.should_stop(max_rows):
            return

        claimed = await asyncio.to_thread(_claim_tier2_work)
        if claimed is None:
            return

        incident_id, raw_message_id = claimed
        try:
            await run_with_ollama_limit(
                run_tier2_detail_fill_for_message,
                raw_message_id,
            )
            stats.record_success()
        except Exception as exc:
            logger.exception(
                "Concurrent tier2 detail fill failed incident_id=%s "
                "raw_message_id=%s error=%s",
                incident_id,
                raw_message_id,
                _format_exception(exc),
            )
            stats.record_failure()


async def sweep_tier2_detail_fill_concurrent(
    *,
    max_rows: int | None = None,
) -> StageSweepResult:
    started_at = time.monotonic()
    stats = _WorkerStats()
    workers = [
        asyncio.create_task(
            _tier2_detail_fill_worker(stats, max_rows=max_rows),
            name=f"tier2-detail-fill-worker-{index}",
        )
        for index in range(_worker_count())
    ]
    await asyncio.gather(*workers)
    elapsed_seconds = time.monotonic() - started_at
    logger.info(
        "Concurrent tier2 detail fill completed processed=%s succeeded=%s failed=%s",
        stats.processed,
        stats.succeeded,
        stats.failed,
    )
    if stats.failed:
        logger.warning(
            "Concurrent tier2 detail fill had failures failed=%s — "
            "details_pending rows may remain; search logs for incident_id / "
            "raw_message_id on prior error lines",
            stats.failed,
        )
    return StageSweepResult(
        stage="tier2_detail_fill",
        processed=stats.processed,
        succeeded=stats.succeeded,
        failed=stats.failed,
        elapsed_seconds=elapsed_seconds,
    )
