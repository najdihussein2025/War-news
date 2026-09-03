from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.news.models import Incident, MessageStatus, RawMessage
from app.news.models.sweep_cursor import LIVE_SWEEP_NAME, SweepCursor
from app.news.repositories.pipeline_claim_repository import claimable_lease_filter
from app.news.services.fast_path_eligibility import fast_path_materializable_clause


@dataclass(frozen=True)
class StageQueueDepth:
    stage_name: str
    queue_depth: int
    oldest_waiting_seconds: float | None


@dataclass(frozen=True)
class CursorGap:
    sweep_name: str
    last_processed_id: int
    max_raw_message_id: int | None
    gap: int
    unhealthy: bool


@dataclass(frozen=True)
class LatencyCohort:
    p50_seconds: float | None
    p95_seconds: float | None
    p99_seconds: float | None
    sample_size: int


@dataclass(frozen=True)
class LatencySummary:
    window_hours: int
    materialized: LatencyCohort
    terminal_non_materialized: LatencyCohort


LATENCY_WINDOW_HOURS = 24

# Terminal statuses that leave the incident pipeline without a materialized
# incident. Kept in a separate latency cohort from the happy path.
_TERMINAL_NON_MATERIALIZED_STATUSES = (
    MessageStatus.routed_air_violation,
    MessageStatus.error,
)


def _has_active_incident_clause():
    return (
        select(Incident.id)
        .where(
            Incident.raw_message_id == RawMessage.id,
            Incident.is_deleted.is_(False),
        )
        .exists()
    )


class PipelineHealthService:
    """Read-only queue-depth / oldest-waiting-age gauges per pipeline stage.

    Each gauge mirrors the corresponding stage's claim-query criteria in
    ``PipelineClaimRepository`` (and the plain-select post stages in
    ``pipeline_sweep_stages``) so the number reflects exactly what that stage
    would pick up on its next pass. The "waiting since" reference uses the
    per-row stage timestamps (item 2): a row waiting for matching has been
    waiting since ``extracted_at``, and so on.

    Clustering is intentionally excluded: it has no row-level claim query to
    mirror (it runs an in-memory clustering pass over all match-eligible rows).
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def stage_queue_depths(self) -> list[StageQueueDepth]:
        now = datetime.now(timezone.utc)
        return [
            self._raw_message_stage(
                "relevance_filter",
                now=now,
                filters=[
                    RawMessage.status == MessageStatus.pending,
                    RawMessage.filter_result.is_(None),
                ],
                waiting_since=RawMessage.received_at,
            ),
            self._raw_message_stage(
                "pre_extraction_dedup",
                now=now,
                filters=[
                    RawMessage.status == MessageStatus.parsed,
                    RawMessage.extraction_result.is_(None),
                    RawMessage.duplicate_of_id.is_(None),
                ],
                waiting_since=func.coalesce(
                    RawMessage.relevance_filtered_at, RawMessage.received_at
                ),
            ),
            self._raw_message_stage(
                "tier1_extraction",
                now=now,
                filters=[
                    claimable_lease_filter(now),
                    RawMessage.status == MessageStatus.parsed,
                    RawMessage.extraction_result.is_(None),
                    RawMessage.duplicate_of_id.is_(None),
                ],
                waiting_since=func.coalesce(
                    RawMessage.dedup_checked_at,
                    RawMessage.relevance_filtered_at,
                    RawMessage.received_at,
                ),
            ),
            self._raw_message_stage(
                "matching",
                now=now,
                filters=[
                    claimable_lease_filter(now),
                    RawMessage.status == MessageStatus.parsed,
                    RawMessage.extraction_result.is_not(None),
                    RawMessage.match_result.is_(None),
                    RawMessage.duplicate_of_id.is_(None),
                ],
                waiting_since=func.coalesce(
                    RawMessage.extracted_at, RawMessage.received_at
                ),
            ),
            self._raw_message_stage(
                "fast_path",
                now=now,
                filters=[
                    RawMessage.status == MessageStatus.parsed,
                    RawMessage.duplicate_of_id.is_(None),
                    RawMessage.match_result.is_not(None),
                    RawMessage.extraction_result.is_not(None),
                    ~_has_active_incident_clause(),
                    fast_path_materializable_clause(),
                ],
                waiting_since=func.coalesce(
                    RawMessage.matched_at, RawMessage.received_at
                ),
            ),
            self._tier2_detail_fill_stage(now=now),
            self._raw_message_stage(
                "embedding",
                now=now,
                filters=[
                    RawMessage.status == MessageStatus.parsed,
                    RawMessage.content_embedding.is_(None),
                ],
                waiting_since=func.coalesce(
                    RawMessage.matched_at,
                    RawMessage.extracted_at,
                    RawMessage.received_at,
                ),
            ),
            self._raw_message_stage(
                "materialization",
                now=now,
                filters=[
                    RawMessage.status == MessageStatus.parsed,
                    RawMessage.duplicate_of_id.is_(None),
                    RawMessage.match_result.is_not(None),
                    ~_has_active_incident_clause(),
                ],
                waiting_since=func.coalesce(
                    RawMessage.matched_at, RawMessage.received_at
                ),
            ),
        ]

    def _raw_message_stage(
        self,
        stage_name: str,
        *,
        now: datetime,
        filters: list,
        waiting_since,
    ) -> StageQueueDepth:
        depth, oldest = self.db.execute(
            select(func.count(), func.min(waiting_since)).where(*filters)
        ).one()
        return StageQueueDepth(
            stage_name=stage_name,
            queue_depth=int(depth or 0),
            oldest_waiting_seconds=self._age_seconds(oldest, now),
        )

    def cursor_gap(self) -> CursorGap:
        """Live-sweep relevance watermark vs rows still awaiting relevance filter.

        ``unhealthy`` is a data field, never a status code: the endpoint
        returns 200 regardless. It flips true when the count of
        relevance-eligible rows (``pending`` with no ``filter_result``) newer
        than the cursor exceeds
        ``settings.pipeline_cursor_gap_row_threshold``, OR the cursor has not
        advanced in ``settings.pipeline_cursor_stale_minutes`` minutes while
        such a backlog exists.

        Pre-classified ingestion (e.g. CNRS webhook rows that arrive already
        ``parsed`` with a ``filter_result``) never enters this backlog, so
        they do not inflate the gap or trigger staleness on their own.
        """
        now = datetime.now(timezone.utc)
        cursor = self.db.get(SweepCursor, LIVE_SWEEP_NAME)
        last_processed_id = int(cursor.last_processed_id) if cursor is not None else 0
        cursor_updated_at = cursor.updated_at if cursor is not None else None

        max_raw_message_id = self.db.execute(
            select(func.max(RawMessage.id))
        ).scalar_one()

        gap = int(
            self.db.execute(
                select(func.count()).where(
                    RawMessage.id > last_processed_id,
                    RawMessage.status == MessageStatus.pending,
                    RawMessage.filter_result.is_(None),
                )
            ).scalar_one()
            or 0
        )
        relevance_backlog_exists = gap > 0

        unhealthy_by_gap = gap > settings.pipeline_cursor_gap_row_threshold

        unhealthy_by_staleness = False
        if relevance_backlog_exists and cursor_updated_at is not None:
            if cursor_updated_at.tzinfo is None:
                cursor_updated_at = cursor_updated_at.replace(tzinfo=timezone.utc)
            stale_after = timedelta(minutes=settings.pipeline_cursor_stale_minutes)
            unhealthy_by_staleness = (now - cursor_updated_at) > stale_after

        return CursorGap(
            sweep_name=LIVE_SWEEP_NAME,
            last_processed_id=last_processed_id,
            max_raw_message_id=max_raw_message_id,
            gap=gap,
            unhealthy=unhealthy_by_gap or unhealthy_by_staleness,
        )

    def latency_summary(self) -> LatencySummary:
        """p50/p95/p99 of received_at -> "done", over a rolling 24h window.

        Two cohorts, kept separate on purpose:

        * ``materialized`` - received_at -> materialized_at. This is the
          happy-path end-to-end latency an SLO would eventually target, and
          the only cohort with a dedicated item-2 "done" timestamp.
        * ``terminal_non_materialized`` - received_at -> matched_at for rows
          that ended in ``routed_air_violation`` or terminal ``error``.
          These take a different, shorter (routing) or long-tailed (error
          retry) journey that would bias the happy-path percentiles, and
          item 2 added no routed_at/errored_at column, so matched_at is used
          as the terminal reference.

        No pass/fail SLO target is emitted - this is human-visible data only.
        Both queries filter on an indexed item-2 timestamp column
        (ix_raw_messages_materialized_at / ix_raw_messages_matched_at).
        """
        window_start = datetime.now(timezone.utc) - timedelta(
            hours=LATENCY_WINDOW_HOURS
        )
        return LatencySummary(
            window_hours=LATENCY_WINDOW_HOURS,
            materialized=self._latency_cohort(
                done_column=RawMessage.materialized_at,
                extra_filters=[RawMessage.materialized_at >= window_start],
            ),
            terminal_non_materialized=self._latency_cohort(
                done_column=RawMessage.matched_at,
                extra_filters=[
                    RawMessage.matched_at >= window_start,
                    RawMessage.status.in_(_TERMINAL_NON_MATERIALIZED_STATUSES),
                ],
            ),
        )

    def _latency_cohort(self, *, done_column, extra_filters: list) -> LatencyCohort:
        elapsed = func.extract("epoch", done_column - RawMessage.received_at)
        p50, p95, p99, sample_size = self.db.execute(
            select(
                func.percentile_cont(0.5).within_group(elapsed.asc()),
                func.percentile_cont(0.95).within_group(elapsed.asc()),
                func.percentile_cont(0.99).within_group(elapsed.asc()),
                func.count(),
            ).where(done_column.is_not(None), *extra_filters)
        ).one()
        return LatencyCohort(
            p50_seconds=float(p50) if p50 is not None else None,
            p95_seconds=float(p95) if p95 is not None else None,
            p99_seconds=float(p99) if p99 is not None else None,
            sample_size=int(sample_size or 0),
        )

    def _tier2_detail_fill_stage(self, *, now: datetime) -> StageQueueDepth:
        depth, oldest = self.db.execute(
            select(func.count(), func.min(Incident.created_at)).where(
                Incident.details_pending.is_(True),
                Incident.is_deleted.is_(False),
            )
        ).one()
        return StageQueueDepth(
            stage_name="tier2_detail_fill",
            queue_depth=int(depth or 0),
            oldest_waiting_seconds=self._age_seconds(oldest, now),
        )

    @staticmethod
    def _age_seconds(oldest: datetime | None, now: datetime) -> float | None:
        if oldest is None:
            return None
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        return max(0.0, (now - oldest).total_seconds())
