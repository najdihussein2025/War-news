from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.news.models import DuplicateMatch, Incident, MessageStatus, RawMessage
from app.news.repositories.incident_repository import IncidentRepository

logger = logging.getLogger(__name__)


def _find_representative_incident(
    db: Session,
    incident_repo: IncidentRepository,
    *,
    soft_deleted: Incident,
) -> Incident | None:
    raw_message = db.get(RawMessage, soft_deleted.raw_message_id)
    if raw_message is None:
        return None

    if raw_message.duplicate_of_id is not None:
        representative = incident_repo.find_active_incident_for_raw_message_village(
            raw_message.duplicate_of_id,
            soft_deleted.village_id,
        )
        if representative is not None:
            return representative

    # Same bulletin cluster: active incident for the village/date from a non-duplicate
    # raw_message (representative may differ in condition_id after re-materialization).
    representative = db.scalar(
        select(Incident)
        .join(RawMessage, RawMessage.id == Incident.raw_message_id)
        .where(
            Incident.village_id == soft_deleted.village_id,
            Incident.event_date == soft_deleted.event_date,
            Incident.is_deleted.is_(False),
            Incident.raw_message_id != soft_deleted.raw_message_id,
            RawMessage.status != MessageStatus.duplicate,
        )
        .order_by(RawMessage.id.asc())
        .limit(1)
    )
    if representative is not None:
        return representative

    return None


def reconcile_orphaned_soft_deleted_incidents(db: Session) -> int:
    """
    Backfill duplicate_matches for soft-deleted incidents that have no link yet.

    Runs after materialization so representative incidents usually exist.
    """
    incident_repo = IncidentRepository(db)
    orphans = list(
        db.scalars(
            select(Incident)
            .outerjoin(DuplicateMatch, DuplicateMatch.incident_id == Incident.id)
            .where(
                Incident.is_deleted.is_(True),
                DuplicateMatch.id.is_(None),
            )
        ).all()
    )

    backfilled = 0
    for incident in orphans:
        representative = _find_representative_incident(
            db,
            incident_repo,
            soft_deleted=incident,
        )
        if representative is None:
            continue

        incident_repo.create_duplicate_match(
            incident=incident,
            matched_incident=representative,
            similarity_score=0.0,
        )
        backfilled += 1
        logger.info(
            "duplicate_match_reconciliation incident_id=%s matched_incident_id=%s "
            "raw_message_id=%s village_id=%s",
            incident.id,
            representative.id,
            incident.raw_message_id,
            incident.village_id,
        )

    if backfilled:
        db.commit()

    return backfilled
