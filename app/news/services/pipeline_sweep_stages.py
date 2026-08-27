from __future__ import annotations

import logging
import time

from sqlalchemy import func, literal, select, text
from sqlalchemy.orm import Session

from app.api.factories.action_factory import (
    build_extract_incidents_action,
    build_filter_relevance_action,
    build_match_incident_action,
)
from app.core.config import settings
from app.llm.services.ollama_auth_failures import OllamaAuthFailure
from app.llm.dtos import ExtractPendingMessagesData, FilterPendingMessagesData
from app.news.dtos.pipeline_dto import StageSweepResult
from app.news.models import MessageStatus, RawMessage
from app.news.repositories.channel_trust_tier_repository import (
    ChannelTrustTierRepository,
)
from app.news.repositories.incident_repository import IncidentRepository
from app.news.repositories.raw_message_repository import RawMessageRepository
from app.news.services.clustering_service import ClusteringService, village_ids_from_match_result
from app.news.services.dedup_matching_service import DedupMatchingService
from app.news.services.duplicate_match_reconciliation import (
    reconcile_orphaned_soft_deleted_incidents,
)
from app.news.services.incident_materialization_service import (
    IncidentMaterializationService,
)
from app.news.services.pre_extraction_dedup import process_pre_dedup_message

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = ExtractPendingMessagesData().batch_size


def _cap_batch_size(
    batch_size: int,
    processed: int,
    max_rows: int | None,
) -> int:
    if max_rows is None:
        return batch_size
    remaining = max_rows - processed
    if remaining <= 0:
        return 0
    return min(batch_size, remaining)


def _format_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return f"{type(exc).__name__} (no message)"


def _count_pending_unfiltered_rows(db: Session) -> int:
    return len(
        list(
            db.scalars(
                select(RawMessage.id).where(
                    RawMessage.status == MessageStatus.pending,
                    RawMessage.filter_result.is_(None),
                )
            ).all()
        )
    )


def _count_pending_extraction_rows(db: Session) -> int:
    return len(
        list(
            db.scalars(
                select(RawMessage.id).where(
                    RawMessage.status == MessageStatus.parsed,
                    RawMessage.extraction_result.is_(None),
                    RawMessage.duplicate_of_id.is_(None),
                )
            ).all()
        )
    )


async def sweep_relevance_filter(
    db: Session,
    *,
    batch_size: int | None = None,
    max_rows: int | None = None,
) -> StageSweepResult:
    started_at = time.monotonic()
    action = build_filter_relevance_action(db)
    default_batch_size = (
        batch_size if batch_size is not None else FilterPendingMessagesData().batch_size
    )

    processed = 0
    succeeded = 0
    failed = 0

    while True:
        if max_rows is not None and processed >= max_rows:
            break

        request_size = _cap_batch_size(default_batch_size, processed, max_rows)
        if request_size <= 0:
            break

        try:
            summary = await action.execute_async(
                FilterPendingMessagesData(batch_size=request_size)
            )
        except OllamaAuthFailure as exc:
            unprocessed = _count_pending_unfiltered_rows(db)
            logger.error(
                "Ollama authentication failed (401) during stage=%s; aborting sweep "
                "pass with %s messages left pending",
                "relevance_filter",
                unprocessed,
            )
            elapsed_seconds = time.monotonic() - started_at
            return StageSweepResult(
                stage="relevance_filter",
                processed=processed,
                succeeded=succeeded,
                failed=failed,
                aborted=True,
                abort_reason=str(exc),
                unprocessed=unprocessed,
                elapsed_seconds=elapsed_seconds,
            )
        if summary.processed == 0:
            break

        processed += summary.processed
        succeeded += summary.relevant + summary.rejected + summary.uncertain
        failed += summary.errored

        if max_rows is not None and processed >= max_rows:
            break

    elapsed_seconds = time.monotonic() - started_at
    return StageSweepResult(
        stage="relevance_filter",
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        elapsed_seconds=elapsed_seconds,
    )


def sweep_pre_extraction_dedup(
    db: Session,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_rows: int | None = None,
) -> StageSweepResult:
    """
    Deduplicates relevance-passed messages before extraction runs.

    Compares each eligible row's raw_text against all non-rejected messages
    received within the last 48 hours using pg_trgm word_similarity.  A row
    whose best similarity score meets the threshold is marked duplicate and
    skipped by sweep_extraction.
    """
    started_at = time.monotonic()
    threshold = settings.pre_dedup_similarity_threshold

    processed = 0
    succeeded = 0
    failed = 0
    last_seen_id = 0

    while True:
        if max_rows is not None and processed >= max_rows:
            break

        request_size = _cap_batch_size(batch_size, processed, max_rows)
        if request_size <= 0:
            break

        raw_message_ids = list(
            db.scalars(
                select(RawMessage.id)
                .where(
                    RawMessage.id > last_seen_id,
                    RawMessage.status == MessageStatus.parsed,
                    RawMessage.extraction_result.is_(None),
                    RawMessage.duplicate_of_id.is_(None),
                )
                .order_by(RawMessage.id.asc())
                .limit(request_size)
            ).all()
        )
        if not raw_message_ids:
            break

        last_seen_id = raw_message_ids[-1]

        for raw_message_id in raw_message_ids:
            if max_rows is not None and processed >= max_rows:
                break

            processed += 1
            try:
                if process_pre_dedup_message(
                    db,
                    raw_message_id=raw_message_id,
                    threshold=threshold,
                ):
                    succeeded += 1
            except Exception as exc:
                db.rollback()
                failed += 1
                logger.error(
                    "raw_message_id=%s pre_extraction_dedup failed: %s",
                    raw_message_id,
                    _format_exception(exc),
                )

        if max_rows is not None and processed >= max_rows:
            break

    elapsed_seconds = time.monotonic() - started_at
    return StageSweepResult(
        stage="pre_extraction_dedup",
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        elapsed_seconds=elapsed_seconds,
    )


def sweep_extraction(
    db: Session,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_rows: int | None = None,
) -> StageSweepResult:
    started_at = time.monotonic()
    action = build_extract_incidents_action(db)

    processed = 0
    succeeded = 0
    failed = 0

    while True:
        if max_rows is not None and processed >= max_rows:
            break

        request_size = _cap_batch_size(batch_size, processed, max_rows)
        if request_size <= 0:
            break

        try:
            summary = action.execute(ExtractPendingMessagesData(batch_size=request_size))
        except OllamaAuthFailure as exc:
            unprocessed = _count_pending_extraction_rows(db)
            logger.error(
                "Ollama authentication failed (401) during stage=%s; aborting sweep "
                "pass with %s messages left pending",
                "extraction",
                unprocessed,
            )
            elapsed_seconds = time.monotonic() - started_at
            return StageSweepResult(
                stage="extraction",
                processed=processed,
                succeeded=succeeded,
                failed=failed,
                aborted=True,
                abort_reason=str(exc),
                unprocessed=unprocessed,
                elapsed_seconds=elapsed_seconds,
            )
        if summary.processed == 0:
            break

        processed += summary.processed
        succeeded += summary.extracted
        failed += summary.errored

        if max_rows is not None and processed >= max_rows:
            break

    elapsed_seconds = time.monotonic() - started_at
    return StageSweepResult(
        stage="extraction",
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        elapsed_seconds=elapsed_seconds,
    )


def sweep_matching(
    db: Session,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    rematch: bool = False,
    max_rows: int | None = None,
) -> StageSweepResult:
    started_at = time.monotonic()
    action = build_match_incident_action(db)
    raw_messages = RawMessageRepository(db)
    reset_count, reset_capped = raw_messages.reset_retryable_matching_errors()
    if reset_count or reset_capped:
        logger.info(
            "Matching retry reset re_queued=%s capped=%s before matching sweep",
            reset_count,
            reset_capped,
        )

    processed = 0
    succeeded = 0
    failed = 0
    last_seen_id = 0

    while True:
        if max_rows is not None and processed >= max_rows:
            break

        query = (
            select(RawMessage.id)
            .where(
                RawMessage.id > last_seen_id,
                RawMessage.status == MessageStatus.parsed,
                RawMessage.extraction_result.is_not(None),
            )
            .order_by(RawMessage.id.asc())
            .limit(_cap_batch_size(batch_size, processed, max_rows))
        )
        if not rematch:
            query = query.where(RawMessage.match_result.is_(None))

        raw_message_ids = list(db.scalars(query).all())
        if not raw_message_ids:
            break

        last_seen_id = raw_message_ids[-1]

        for raw_message_id in raw_message_ids:
            if max_rows is not None and processed >= max_rows:
                break

            processed += 1
            try:
                action.execute(raw_message_id)
                succeeded += 1
            except Exception as exc:
                db.rollback()
                message = raw_messages.get_by_id(raw_message_id)
                if (
                    message is not None
                    and message.status == MessageStatus.parsed
                    and message.extraction_result is not None
                    and message.match_result is None
                ):
                    raw_messages.record_transient_matching_failure(message, exc)
                failed += 1
                logger.error(
                    "raw_message_id=%s matching failed: %s",
                    raw_message_id,
                    _format_exception(exc),
                )

        if max_rows is not None and processed >= max_rows:
            break

    elapsed_seconds = time.monotonic() - started_at
    return StageSweepResult(
        stage="matching",
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        elapsed_seconds=elapsed_seconds,
    )


def sweep_embedding_generation(
    db: Session,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_rows: int | None = None,
) -> StageSweepResult:
    from app.news.services.embedding_service import EmbeddingService
    from app.news.services.raw_message_embedding_service import (
        RawMessageEmbeddingService,
    )

    started_at = time.monotonic()
    repository = RawMessageRepository(db)
    service = RawMessageEmbeddingService(EmbeddingService())

    processed = 0
    succeeded = 0
    failed = 0
    last_seen_id = 0

    while True:
        if max_rows is not None and processed >= max_rows:
            break

        request_size = _cap_batch_size(batch_size, processed, max_rows)
        if request_size <= 0:
            break

        raw_message_ids = list(
            db.scalars(
                select(RawMessage.id)
                .where(
                    RawMessage.id > last_seen_id,
                    RawMessage.status == MessageStatus.parsed,
                    RawMessage.content_embedding.is_(None),
                )
                .order_by(RawMessage.id.asc())
                .limit(request_size)
            ).all()
        )
        if not raw_message_ids:
            break

        last_seen_id = raw_message_ids[-1]

        for raw_message_id in raw_message_ids:
            if max_rows is not None and processed >= max_rows:
                break

            processed += 1
            try:
                message = db.get(RawMessage, raw_message_id)
                if message is None:
                    raise ValueError(f"RawMessage id={raw_message_id} not found")
                embedding = service.generate(message)
                repository.save_content_embedding(
                    raw_message_id=raw_message_id,
                    embedding=embedding,
                )
                succeeded += 1
            except Exception as exc:
                repository.rollback()
                failed += 1
                logger.error(
                    "raw_message_id=%s embedding failed: %s",
                    raw_message_id,
                    _format_exception(exc),
                )

        if max_rows is not None and processed >= max_rows:
            break

    elapsed_seconds = time.monotonic() - started_at
    return StageSweepResult(
        stage="embedding",
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        elapsed_seconds=elapsed_seconds,
    )


def cluster_all_eligible(
    db: Session,
    service: ClusteringService,
    *,
    max_rows: int | None = None,
) -> list[list[RawMessage]]:
    query = (
        select(RawMessage)
        .where(
            RawMessage.status == MessageStatus.parsed,
            RawMessage.content_embedding.is_not(None),
            RawMessage.match_result.is_not(None),
            RawMessage.duplicate_of_id.is_(None),
        )
        .order_by(RawMessage.id.asc())
    )
    if max_rows is not None:
        query = query.limit(max_rows)

    messages = list(db.scalars(query).all())
    return service.cluster_batch(messages)


def sweep_clustering(
    db: Session,
    *,
    max_rows: int | None = None,
) -> StageSweepResult:
    started_at = time.monotonic()
    repository = RawMessageRepository(db)
    incident_repository = IncidentRepository(db)
    service = ClusteringService(
        db=db,
        channel_trust_tiers=ChannelTrustTierRepository(db),
    )

    processed = 0
    succeeded = 0
    failed = 0

    clusters = cluster_all_eligible(db, service, max_rows=max_rows)
    processed = sum(len(cluster) for cluster in clusters)

    for cluster in clusters:
        if len(cluster) == 1:
            succeeded += 1
            continue

        representative_id: int | None = None
        try:
            representative = service.pick_representative(cluster)
            representative_id = representative.id
            rep_village_ids = village_ids_from_match_result(representative.match_result)

            # Materialize the representative before soft-deleting member incidents so
            # duplicate_matches can be written immediately when possible.
            materialization_service = IncidentMaterializationService(
                db,
                dedup_service=DedupMatchingService(incident_repository),
            )
            materialization_service.materialize(representative)

            fully_subsumed_member_ids: list[int] = []
            partial_members: list[tuple[int, frozenset[int]]] = []

            for member in cluster:
                if member.id == representative_id:
                    continue
                member_village_ids = village_ids_from_match_result(member.match_result)
                shared = member_village_ids & rep_village_ids

                if not member_village_ids:
                    # Old-shape or no villages — treat as fully subsumed (backward compat).
                    fully_subsumed_member_ids.append(member.id)
                elif shared == member_village_ids:
                    # All villages of this member are covered by the representative.
                    fully_subsumed_member_ids.append(member.id)
                elif shared:
                    # Only some villages are shared — soft-delete per village only.
                    partial_members.append((member.id, shared))
                # else: no shared village IDs (transitivity edge case) — skip.

            if fully_subsumed_member_ids:
                repository.mark_cluster_duplicates(
                    representative_id=representative_id,
                    member_ids=fully_subsumed_member_ids,
                    commit=False,
                )
                for member_id in fully_subsumed_member_ids:
                    incident_repository.soft_delete_for_raw_message_id(
                        member_id,
                        representative_raw_message_id=representative_id,
                    )

            for member_id, shared_village_ids in partial_members:
                for village_id in shared_village_ids:
                    representative_incident = (
                        incident_repository.find_active_incident_for_raw_message_village(
                            representative_id,
                            village_id,
                        )
                    )
                    incident_repository.soft_delete_for_village_incident(
                        member_id,
                        village_id,
                        matched_incident_id=(
                            representative_incident.id
                            if representative_incident is not None
                            else None
                        ),
                    )

            db.commit()
            all_member_ids = fully_subsumed_member_ids + [m for m, _ in partial_members]
            succeeded += len(cluster)
            logger.info(
                "Cluster formed representative_id=%s member_ids=%s member_count=%s "
                "fully_subsumed=%s partial=%s",
                representative_id,
                all_member_ids,
                len(cluster),
                len(fully_subsumed_member_ids),
                len(partial_members),
            )
        except Exception as exc:
            repository.rollback()
            failed += len(cluster)
            logger.error(
                "Cluster failed representative_id=%s error=%s",
                representative_id,
                _format_exception(exc),
            )

    elapsed_seconds = time.monotonic() - started_at
    return StageSweepResult(
        stage="clustering",
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        elapsed_seconds=elapsed_seconds,
    )


def sweep_materialization(
    db: Session,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_rows: int | None = None,
) -> StageSweepResult:
    started_at = time.monotonic()
    incident_repo = IncidentRepository(db)
    dedup_service = DedupMatchingService(incident_repository=incident_repo)
    service = IncidentMaterializationService(db, dedup_service=dedup_service)

    processed = 0
    failed = 0
    last_seen_id = 0

    while True:
        if max_rows is not None and processed >= max_rows:
            break

        request_size = _cap_batch_size(batch_size, processed, max_rows)
        if request_size <= 0:
            break

        batch = list(
            db.scalars(
                select(RawMessage)
                .where(
                    RawMessage.id > last_seen_id,
                    RawMessage.status == MessageStatus.parsed,
                    RawMessage.duplicate_of_id.is_(None),
                    RawMessage.match_result.is_not(None),
                )
                .order_by(RawMessage.id.asc())
                .limit(request_size)
            ).all()
        )
        if not batch:
            break

        last_seen_id = batch[-1].id

        for representative in batch:
            if max_rows is not None and processed >= max_rows:
                break

            processed += 1
            try:
                service.materialize(representative)
            except Exception as exc:
                db.rollback()
                failed += 1
                logger.error(
                    "raw_message_id=%s materialization failed: %s",
                    representative.id,
                    _format_exception(exc),
                )

        if max_rows is not None and processed >= max_rows:
            break

    reconciled = reconcile_orphaned_soft_deleted_incidents(db)
    logger.info(
        "duplicate_match_reconciliation backfilled=%s",
        reconciled,
    )

    succeeded = (
        service.stats.inserted
        + service.stats.skipped_ineligible
        + service.stats.skipped_air_violation_routed
        + service.stats.skipped_duplicate_hash
        + service.stats.merged_into_existing
    )
    elapsed_seconds = time.monotonic() - started_at
    logger.info(
        "Materialization totals inserted=%s skipped_ineligible=%s "
        "skipped_air_violation_routed=%s skipped_duplicate_hash=%s "
        "merged_into_existing=%s failed=%s",
        service.stats.inserted,
        service.stats.skipped_ineligible,
        service.stats.skipped_air_violation_routed,
        service.stats.skipped_duplicate_hash,
        service.stats.merged_into_existing,
        failed,
    )
    return StageSweepResult(
        stage="materialization",
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        elapsed_seconds=elapsed_seconds,
    )
