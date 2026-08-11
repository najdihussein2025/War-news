from datetime import date, timedelta
from typing import Any

from sqlalchemy import Float, and_, case, cast, desc, func, literal, select
from sqlalchemy.orm import Session

from app.models.news import Incident, IncidentUpdate, UpdateAction

# First estimate; tune after reviewing real duplicate decisions.
DEDUP_TIME_WINDOW_DAYS = 3
# First estimate; scores at or above this are merged into the existing incident.
DEDUP_HIGH_THRESHOLD = 0.80
# First estimate; scores at or below this create an unflagged new incident.
DEDUP_LOW_THRESHOLD = 0.50
# First estimate; action agreement weight in the total duplicate score.
WEIGHT_ACTION_MATCH = 0.35
# First estimate; semantic text similarity weight in the total duplicate score.
WEIGHT_EMBEDDING_SIMILARITY = 0.45
# First estimate; event-date closeness weight in the total duplicate score.
WEIGHT_TIME_CLOSENESS = 0.20

assert (
    WEIGHT_ACTION_MATCH + WEIGHT_EMBEDDING_SIMILARITY + WEIGHT_TIME_CLOSENESS
) == 1.0


def find_best_match(
    db: Session,
    village_id: int,
    condition_id: int,
    event_date: date,
    khabar_embedding: list[float],
) -> tuple[Incident | None, float]:
    start_date = event_date - timedelta(days=DEDUP_TIME_WINDOW_DAYS)
    end_date = event_date + timedelta(days=DEDUP_TIME_WINDOW_DAYS)

    action_score = (
        case((Incident.condition_id == condition_id, 1.0), else_=0.0)
        * WEIGHT_ACTION_MATCH
    )
    embedding_score = (
        (1.0 - Incident.khabar_embedding.cosine_distance(khabar_embedding))
        * WEIGHT_EMBEDDING_SIMILARITY
    )
    days_apart = cast(func.abs(Incident.event_date - literal(event_date)), Float)
    time_score = (
        (1.0 - (days_apart / float(DEDUP_TIME_WINDOW_DAYS))) * WEIGHT_TIME_CLOSENESS
    )
    total_score = (action_score + embedding_score + time_score).label("total_score")

    row = db.execute(
        select(Incident, total_score)
        .where(
            and_(
                Incident.village_id == village_id,
                Incident.is_deleted.is_(False),
                Incident.event_date >= start_date,
                Incident.event_date <= end_date,
                Incident.khabar_embedding.is_not(None),
            )
        )
        .order_by(desc(total_score))
        .limit(1)
    ).first()
    if row is None:
        return None, 0.0

    incident, score = row
    return incident, float(score or 0.0)


def merge_into_incident(
    db: Session,
    existing: Incident,
    new_candidate_data: dict[str, Any],
    raw_message_id: int,
) -> None:
    old_values = _snapshot_merge_fields(existing)

    existing.deaths = _max_preserving_empty(existing.deaths, new_candidate_data.get("deaths"))
    existing.total_deaths = _max_preserving_empty(
        existing.total_deaths,
        new_candidate_data.get("deaths"),
    )
    existing.injuries = _max_preserving_empty(
        existing.injuries,
        new_candidate_data.get("injuries"),
    )
    existing.total_injuries = _max_preserving_empty(
        existing.total_injuries,
        new_candidate_data.get("injuries"),
    )

    khabar = new_candidate_data.get("khabar")
    if khabar:
        existing.note = _append_note(existing.note, khabar, raw_message_id)

    new_values = _snapshot_merge_fields(existing)
    if old_values != new_values:
        db.add(
            IncidentUpdate(
                incident_id=existing.id,
                action=UpdateAction.edit,
                old_values=old_values,
                new_values=new_values,
                performed_by=None,
            )
        )
    db.add(existing)


def _max_preserving_empty(current: int | None, incoming: int | None) -> int | None:
    if current is None and incoming is None:
        return None
    return max(current or 0, incoming or 0)


def _append_note(existing_note: str | None, khabar: str, raw_message_id: int) -> str:
    appended = f"Automated duplicate merge from raw_message_id={raw_message_id}:\n{khabar}"
    if not existing_note:
        return appended
    return f"{existing_note}\n\n{appended}"


def _snapshot_merge_fields(incident: Incident) -> dict[str, Any]:
    return {
        "deaths": incident.deaths,
        "total_deaths": incident.total_deaths,
        "injuries": incident.injuries,
        "total_injuries": incident.total_injuries,
        "note": incident.note,
    }
