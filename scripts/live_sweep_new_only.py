from __future__ import annotations

import asyncio
import logging
import time
from contextlib import ExitStack
from typing import Any
from unittest.mock import patch

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging_config import configure_logging
from app.news.dtos.pipeline_dto import StageSweepResult
from app.news.models import Incident, MessageStatus, RawMessage
from app.news.repositories.pipeline_claim_repository import PipelineClaimRepository
from app.news.repositories.raw_message_repository import RawMessageRepository
from app.news.services.fast_path_eligibility import (
    fast_path_materializable_clause,
    permanent_ineligibility_reason,
)
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

CUTOFF_RAW_MESSAGE_ID = 695974
MAX_ROWS: int | None = None


class FilteredSession:
    """Process-local session wrapper for sync stage eligibility queries."""

    def __init__(self, session: Session, cutoff_raw_message_id: int) -> None:
        self._session = session
        self._cutoff_raw_message_id = cutoff_raw_message_id

    def scalars(self, statement, *args, **kwargs):
        if self._selects_raw_message(statement):
            statement = statement.where(RawMessage.id > self._cutoff_raw_message_id)
        return self._session.scalars(statement, *args, **kwargs)

    @staticmethod
    def _selects_raw_message(statement) -> bool:
        descriptions = getattr(statement, "column_descriptions", None) or []
        return any(desc.get("entity") is RawMessage for desc in descriptions)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


def _get_pending_unfiltered_batch_filtered(
    self: RawMessageRepository,
    limit: int,
) -> list[RawMessage]:
    return list(
        self.db.scalars(
            select(RawMessage)
            .options(joinedload(RawMessage.source))
            .where(
                RawMessage.id > CUTOFF_RAW_MESSAGE_ID,
                RawMessage.status == MessageStatus.pending,
                RawMessage.filter_result.is_(None),
            )
            .order_by(RawMessage.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
    )


def _get_pending_extraction_batch_filtered(
    self: RawMessageRepository,
    limit: int,
) -> list[RawMessage]:
    return list(
        self.db.scalars(
            select(RawMessage)
            .where(
                RawMessage.id > CUTOFF_RAW_MESSAGE_ID,
                RawMessage.status == MessageStatus.parsed,
                RawMessage.extraction_result.is_(None),
                RawMessage.duplicate_of_id.is_(None),
            )
            .order_by(RawMessage.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
    )


def _reset_retryable_extraction_errors_filtered(
    self: RawMessageRepository,
    limit: int = 200,
    *,
    max_retries: int | None = None,
) -> tuple[int, int]:
    retry_limit = (
        max_retries
        if max_retries is not None
        else settings.extraction_max_retries
    )

    messages = list(
        self.db.scalars(
            select(RawMessage)
            .where(
                RawMessage.id > CUTOFF_RAW_MESSAGE_ID,
                RawMessage.status == MessageStatus.error,
                RawMessage.extraction_result.is_(None),
                RawMessage.error_message.is_not(None),
                or_(
                    RawMessage.error_message.ilike("%ReadTimeout%"),
                    RawMessage.error_message.ilike("%ConnectTimeout%"),
                    RawMessage.error_message.ilike("%TimeoutException%"),
                    RawMessage.error_message.ilike("%timed out%"),
                ),
            )
            .order_by(RawMessage.id.asc())
            .limit(limit)
        ).all()
    )
    if not messages:
        return 0, 0

    reset_count = 0
    capped_count = 0
    for message in messages:
        if message.extraction_retry_count >= retry_limit:
            if not (message.error_message or "").startswith(
                "extraction: exceeded max retries"
            ):
                from app.llm.services.transient_llm_errors import (
                    extraction_retry_cap_message,
                )

                message.error_message = extraction_retry_cap_message(
                    message.extraction_retry_count,
                    RuntimeError(message.error_message or "timed out"),
                )
                self.db.add(message)
            capped_count += 1
            continue

        message.status = MessageStatus.parsed
        message.error_message = None
        self.db.add(message)
        reset_count += 1

    if reset_count or capped_count:
        self.db.commit()
    return reset_count, capped_count


def _claim_pending_pre_dedup_filtered(
    self: PipelineClaimRepository,
) -> RawMessage | None:
    return self.db.scalar(
        select(RawMessage)
        .where(
            RawMessage.id > CUTOFF_RAW_MESSAGE_ID,
            RawMessage.status == MessageStatus.parsed,
            RawMessage.extraction_result.is_(None),
            RawMessage.duplicate_of_id.is_(None),
        )
        .order_by(RawMessage.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def _claim_pending_extraction_filtered(
    self: PipelineClaimRepository,
) -> RawMessage | None:
    return self.db.scalar(
        select(RawMessage)
        .where(
            RawMessage.id > CUTOFF_RAW_MESSAGE_ID,
            RawMessage.status == MessageStatus.parsed,
            RawMessage.extraction_result.is_(None),
            RawMessage.duplicate_of_id.is_(None),
        )
        .order_by(RawMessage.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def _claim_pending_match_filtered(
    self: PipelineClaimRepository,
) -> RawMessage | None:
    return self.db.scalar(
        select(RawMessage)
        .where(
            RawMessage.id > CUTOFF_RAW_MESSAGE_ID,
            RawMessage.status == MessageStatus.parsed,
            RawMessage.extraction_result.is_not(None),
            RawMessage.match_result.is_(None),
            RawMessage.duplicate_of_id.is_(None),
        )
        .order_by(RawMessage.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def _claim_pending_fast_path_filtered(
    self: PipelineClaimRepository,
) -> RawMessage | None:
    has_active_incident = (
        select(Incident.id)
        .where(
            Incident.raw_message_id == RawMessage.id,
            Incident.is_deleted.is_(False),
        )
        .exists()
    )
    return self.db.scalar(
        select(RawMessage)
        .where(
            RawMessage.id > CUTOFF_RAW_MESSAGE_ID,
            RawMessage.status == MessageStatus.parsed,
            RawMessage.duplicate_of_id.is_(None),
            RawMessage.match_result.is_not(None),
            RawMessage.extraction_result.is_not(None),
            ~has_active_incident,
            fast_path_materializable_clause(),
        )
        .order_by(RawMessage.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def _claim_pending_tier2_detail_fill_filtered(
    self: PipelineClaimRepository,
) -> Incident | None:
    return self.db.scalar(
        select(Incident)
        .join(RawMessage, RawMessage.id == Incident.raw_message_id)
        .where(
            Incident.details_pending.is_(True),
            Incident.is_deleted.is_(False),
            RawMessage.id > CUTOFF_RAW_MESSAGE_ID,
        )
        .order_by(Incident.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def _terminalize_ineligible_fast_path_filtered(
    self: PipelineClaimRepository,
) -> int:
    has_active_incident = (
        select(Incident.id)
        .where(
            Incident.raw_message_id == RawMessage.id,
            Incident.is_deleted.is_(False),
        )
        .exists()
    )
    messages = list(
        self.db.scalars(
            select(RawMessage)
            .where(
                RawMessage.id > CUTOFF_RAW_MESSAGE_ID,
                RawMessage.status == MessageStatus.parsed,
                RawMessage.duplicate_of_id.is_(None),
                RawMessage.match_result.is_not(None),
                RawMessage.extraction_result.is_not(None),
                ~has_active_incident,
            )
            .order_by(RawMessage.id.asc())
        ).all()
    )
    if not messages:
        return 0

    updated = 0
    for message in messages:
        reason = permanent_ineligibility_reason(message.match_result)
        if reason is None:
            continue
        message.status = MessageStatus.error
        message.error_message = reason
        self.db.add(message)
        updated += 1

    if updated:
        self.db.commit()
    else:
        self.db.rollback()
    return updated


def _apply_process_local_filter_patches() -> ExitStack:
    stack = ExitStack()
    stack.enter_context(
        patch.object(
            RawMessageRepository,
            "get_pending_unfiltered_batch",
            _get_pending_unfiltered_batch_filtered,
        )
    )
    stack.enter_context(
        patch.object(
            RawMessageRepository,
            "get_pending_extraction_batch",
            _get_pending_extraction_batch_filtered,
        )
    )
    stack.enter_context(
        patch.object(
            RawMessageRepository,
            "reset_retryable_extraction_errors",
            _reset_retryable_extraction_errors_filtered,
        )
    )
    stack.enter_context(
        patch.object(
            PipelineClaimRepository,
            "claim_pending_pre_dedup",
            _claim_pending_pre_dedup_filtered,
        )
    )
    stack.enter_context(
        patch.object(
            PipelineClaimRepository,
            "claim_pending_extraction",
            _claim_pending_extraction_filtered,
        )
    )
    stack.enter_context(
        patch.object(
            PipelineClaimRepository,
            "claim_pending_match",
            _claim_pending_match_filtered,
        )
    )
    stack.enter_context(
        patch.object(
            PipelineClaimRepository,
            "claim_pending_fast_path",
            _claim_pending_fast_path_filtered,
        )
    )
    stack.enter_context(
        patch.object(
            PipelineClaimRepository,
            "claim_pending_tier2_detail_fill",
            _claim_pending_tier2_detail_fill_filtered,
        )
    )
    stack.enter_context(
        patch.object(
            PipelineClaimRepository,
            "terminalize_ineligible_fast_path",
            _terminalize_ineligible_fast_path_filtered,
        )
    )
    return stack


def _emit_stage_result(result: StageSweepResult) -> None:
    line = (
        f"Pipeline stage={result.stage} processed={result.processed} "
        f"succeeded={result.succeeded} failed={result.failed} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}"
    )
    logger.info("%s cutoff_raw_message_id=%s", line, CUTOFF_RAW_MESSAGE_ID)
    print(line, flush=True)


async def _run_async_stage(stage_name: str, sweep_fn) -> StageSweepResult:
    started_at = time.monotonic()
    try:
        return await sweep_fn(max_rows=MAX_ROWS)
    except Exception:
        logger.exception(
            "Pipeline stage=%s failed cutoff_raw_message_id=%s",
            stage_name,
            CUTOFF_RAW_MESSAGE_ID,
        )
        return StageSweepResult(
            stage=stage_name,
            processed=0,
            succeeded=0,
            failed=1,
            elapsed_seconds=time.monotonic() - started_at,
        )


async def _run_async_stage_with_db(stage_name: str, sweep_fn) -> StageSweepResult:
    started_at = time.monotonic()
    with SessionLocal() as db:
        filtered_db = FilteredSession(db, CUTOFF_RAW_MESSAGE_ID)
        try:
            return await sweep_fn(filtered_db, max_rows=MAX_ROWS)
        except Exception:
            logger.exception(
                "Pipeline stage=%s failed cutoff_raw_message_id=%s",
                stage_name,
                CUTOFF_RAW_MESSAGE_ID,
            )
            return StageSweepResult(
                stage=stage_name,
                processed=0,
                succeeded=0,
                failed=1,
                elapsed_seconds=time.monotonic() - started_at,
            )


def _run_sync_stage(stage_name: str, sweep_fn) -> StageSweepResult:
    started_at = time.monotonic()
    with SessionLocal() as db:
        filtered_db = FilteredSession(db, CUTOFF_RAW_MESSAGE_ID)
        try:
            return sweep_fn(filtered_db, max_rows=MAX_ROWS)
        except Exception:
            logger.exception(
                "Pipeline stage=%s failed cutoff_raw_message_id=%s",
                stage_name,
                CUTOFF_RAW_MESSAGE_ID,
            )
            return StageSweepResult(
                stage=stage_name,
                processed=0,
                succeeded=0,
                failed=1,
                elapsed_seconds=time.monotonic() - started_at,
            )


async def main() -> int:
    configure_logging()
    logger.info(
        "Starting one-pass new-only live sweep cutoff_raw_message_id=%s",
        CUTOFF_RAW_MESSAGE_ID,
    )

    stages: list[StageSweepResult] = []
    with _apply_process_local_filter_patches():
        stages.append(
            await _run_async_stage_with_db("relevance_filter", sweep_relevance_filter)
        )
        stages.append(
            await _run_async_stage("pre_extraction_dedup", sweep_pre_dedup_concurrent)
        )
        stages.append(
            await _run_async_stage("tier1_extraction", sweep_extraction_concurrent)
        )
        stages.append(await _run_async_stage("matching", sweep_matching_concurrent))
        stages.append(await _run_async_stage("fast_path", sweep_fast_path_concurrent))
        stages.append(
            await _run_async_stage(
                "tier2_detail_fill",
                sweep_tier2_detail_fill_concurrent,
            )
        )
        stages.append(_run_sync_stage("embedding", sweep_embedding_generation))
        stages.append(_run_sync_stage("clustering", sweep_clustering))
        stages.append(_run_sync_stage("materialization", sweep_materialization))

    for result in stages:
        _emit_stage_result(result)

    logger.info(
        "Completed one-pass new-only live sweep cutoff_raw_message_id=%s",
        CUTOFF_RAW_MESSAGE_ID,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
