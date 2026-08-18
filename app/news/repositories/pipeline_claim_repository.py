from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.news.models import Incident, MessageStatus, RawMessage
from app.news.services.fast_path_eligibility import (
    fast_path_materializable_clause,
    ineligible_fast_path_update_sql,
)


class PipelineClaimRepository:
    """Row-level work claiming via SELECT ... FOR UPDATE SKIP LOCKED."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def claim_pending_unfiltered(self) -> RawMessage | None:
        return self.db.scalar(
            select(RawMessage)
            .where(
                RawMessage.status == MessageStatus.pending,
                RawMessage.filter_result.is_(None),
            )
            .order_by(RawMessage.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )

    def claim_pending_pre_dedup(self) -> RawMessage | None:
        return self.db.scalar(
            select(RawMessage)
            .where(
                RawMessage.status == MessageStatus.parsed,
                RawMessage.extraction_result.is_(None),
                RawMessage.duplicate_of_id.is_(None),
            )
            .order_by(RawMessage.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )

    def claim_pending_extraction(self) -> RawMessage | None:
        return self.db.scalar(
            select(RawMessage)
            .where(
                RawMessage.status == MessageStatus.parsed,
                RawMessage.extraction_result.is_(None),
                RawMessage.duplicate_of_id.is_(None),
            )
            .order_by(RawMessage.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )

    def claim_pending_match(self) -> RawMessage | None:
        return self.db.scalar(
            select(RawMessage)
            .where(
                RawMessage.status == MessageStatus.parsed,
                RawMessage.extraction_result.is_not(None),
                RawMessage.match_result.is_(None),
                RawMessage.duplicate_of_id.is_(None),
            )
            .order_by(RawMessage.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )

    def claim_pending_fast_path(self) -> RawMessage | None:
        """Messages ready for fast materialization that have no active incidents yet."""
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

    def terminalize_ineligible_fast_path(self) -> int:
        """Mark permanently unmaterializable matched rows so they are never reclaimed."""
        result = self.db.execute(ineligible_fast_path_update_sql())
        self.db.commit()
        return int(result.rowcount or 0)

    def claim_pending_legacy_materialization(self) -> RawMessage | None:
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
                RawMessage.status == MessageStatus.parsed,
                RawMessage.duplicate_of_id.is_(None),
                RawMessage.match_result.is_not(None),
                ~has_active_incident,
            )
            .order_by(RawMessage.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )

    def claim_pending_tier2_detail_fill(self) -> Incident | None:
        return self.db.scalar(
            select(Incident)
            .where(
                Incident.details_pending.is_(True),
                Incident.is_deleted.is_(False),
            )
            .order_by(Incident.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
