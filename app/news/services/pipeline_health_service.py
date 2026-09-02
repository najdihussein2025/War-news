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
        """Live-sweep watermark vs MAX(raw_messages.id).

        ``unhealthy`` is a data field, never a status code: the endpoint
        returns 200 regardless. It flips true when the cursor trails the
        newest raw_message by more than
        ``settings.pipeline_cursor_gap_row_threshold`` rows, OR the cursor
        has not advanced in ``settings.pipeline_cursor_stale_minutes``
        minutes while newer rows exist.
        """
        now = datetime.now(timezone.utc)
        cursor = self.db.get(SweepCursor, LIVE_SWEEP_NAME)
        last_processed_id = int(cursor.last_processed_id) if cursor is not None else 0
        cursor_updated_at = cursor.updated_at if cursor is not None else None

        max_raw_message_id = self.db.execute(
            select(func.max(RawMessage.id))
        ).scalar_one()

        gap = max(0, (max_raw_message_id or 0) - last_processed_id)
        newer_rows_exist = gap > 0

        unhealthy_by_gap = gap > settings.pipeline_cursor_gap_row_threshold

        unhealthy_by_staleness = False
        if newer_rows_exist and cursor_updated_at is not None:
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
