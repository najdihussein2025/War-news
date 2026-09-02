from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.news.models import Incident, MessageStatus, RawMessage
from app.news.services.fast_path_eligibility import (
    fast_path_materializable_clause,
    ineligible_fast_path_update_sql,
)

CLAIM_STAGE_EXTRACTION = "tier1_extraction"
CLAIM_STAGE_MATCHING = "matching"


def claimable_lease_filter(now: datetime | None = None):
    """OR-predicate for a raw_message whose processing claim is free or expired.

    Single source of truth shared by the claim repository and read-only
    health checks so the two cannot drift.
    """
    reference = now or datetime.now(timezone.utc)
    cutoff = reference - timedelta(seconds=settings.pipeline_claim_lease_seconds)
    return (
        RawMessage.processing_claimed_at.is_(None)
        | (RawMessage.processing_claimed_at < cutoff)
        | (RawMessage.processing_claim_stage.is_(None))
    )


class PipelineClaimRepository:
    """Row-level work claiming via SELECT ... FOR UPDATE SKIP LOCKED."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _claim_owner(self) -> str:
        return (
            f"{settings.pipeline_role}:pid={os.getpid()}:thread={threading.get_ident()}"
        )

    def _claimable_raw_messages(self):
        return select(RawMessage).where(claimable_lease_filter())

    def _mark_claimed(self, message: RawMessage, *, stage: str) -> RawMessage:
        message.processing_claim_stage = stage
        message.processing_claimed_at = datetime.now(timezone.utc)
        message.processing_claimed_by = self._claim_owner()
        self.db.add(message)
        return message

    def release_claim(self, raw_message_id: int) -> bool:
        message = self.db.get(RawMessage, raw_message_id)
        if message is None:
            return False
        message.processing_claim_stage = None
        message.processing_claimed_at = None
        message.processing_claimed_by = None
        self.db.add(message)
        self.db.commit()
        return True

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
        message = self.db.scalar(
            self._claimable_raw_messages()
            .where(
                RawMessage.status == MessageStatus.parsed,
                RawMessage.extraction_result.is_(None),
                RawMessage.duplicate_of_id.is_(None),
            )
            .order_by(RawMessage.id.desc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if message is None:
            return None
        return self._mark_claimed(message, stage=CLAIM_STAGE_EXTRACTION)

    def claim_pending_match(self) -> RawMessage | None:
        message = self.db.scalar(
            self._claimable_raw_messages()
            .where(
                RawMessage.status == MessageStatus.parsed,
                RawMessage.extraction_result.is_not(None),
                RawMessage.match_result.is_(None),
                RawMessage.duplicate_of_id.is_(None),
            )
            .order_by(RawMessage.id.desc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if message is None:
            return None
        return self._mark_claimed(message, stage=CLAIM_STAGE_MATCHING)

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
