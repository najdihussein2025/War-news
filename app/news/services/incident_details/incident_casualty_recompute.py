"""Single, idempotent writer for derived incident casualty totals."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.news.models.incident import Incident
from app.news.models.incident_detail import IncidentDetail
from app.news.models.incident_update import IncidentUpdate, UpdateAction
from app.news.models.raw_message import RawMessage
from app.news.models.duplicate_match import DuplicateMatch

FIELDS = ("deaths", "injuries", "total_deaths", "total_injuries")
REASON_CODES = frozenset({"created", "merged", "revision", "transition", "reconciled", "repair"})


@dataclass(frozen=True)
class ConnectedCasualtySource:
    raw_message_id: int
    text: str
    source: str | None
    received_at: object | None
    origin: str


def connected_casualty_sources(db: Session, incident: Incident) -> list[ConnectedCasualtySource]:
    """Return live raws and retained merge snapshots, without inventing sources."""
    ids = {incident.raw_message_id} if incident.raw_message_id else set()
    snapshots: dict[int, ConnectedCasualtySource] = {}
    for match in db.scalars(select(DuplicateMatch).where(or_(DuplicateMatch.incident_id == incident.id, DuplicateMatch.matched_incident_id == incident.id))):
        if match.raw_message_id:
            ids.add(match.raw_message_id)
    for update in db.scalars(select(IncidentUpdate).where(IncidentUpdate.incident_id == incident.id)):
        merged = (update.new_values or {}).get("merged_from")
        if isinstance(merged, dict) and isinstance(merged.get("raw_message_id"), int) and isinstance(merged.get("khabar"), str):
            raw_id = merged["raw_message_id"]
            ids.add(raw_id)
            snapshots[raw_id] = ConnectedCasualtySource(raw_id, merged["khabar"], merged.get("channel"), update.created_at, "merged_from_snapshot")
    live = {raw.id: raw for raw in db.scalars(select(RawMessage).where(RawMessage.id.in_(ids)))} if ids else {}
    sources = [ConnectedCasualtySource(raw.id, raw.raw_text or "", str(raw.source_id) if raw.source_id else None, raw.received_at, "raw_messages") for raw in live.values()]
    sources.extend(snapshot for raw_id, snapshot in snapshots.items() if raw_id not in live)
    return sorted(sources, key=lambda item: (str(item.received_at), item.raw_message_id))


def derived_total(*values: int | None) -> int | None:
    """Return the largest supported local/demo total without inventing zero."""
    present = [value for value in values if value is not None]
    return max(present) if present else None


def demographic_total(*values: int | None) -> int | None:
    """Sum explicitly populated demographic fields, retaining null when absent."""
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def recompute_incident_casualties(db: Session, incident: Incident, *, raw_message_ids: list[int] | None = None, reason_code: str = "reconciled", creating: bool = False) -> bool:
    """Derive totals from local values/demographics and emit one audit row.

    Admin edits win: an audited human casualty edit makes this a no-op.  This
    narrow writer is safe to call repeatedly; it never adds values from raws.
    """
    if reason_code not in REASON_CODES:
        raise ValueError(f"unsupported automatic casualty reason_code: {reason_code!r}")
    scalars = getattr(db, "scalars", None)
    edited = scalars(select(IncidentUpdate.new_values).where(IncidentUpdate.incident_id == incident.id, IncidentUpdate.action == UpdateAction.edit, IncidentUpdate.performed_by.is_not(None))).all() if scalars else []
    if any(isinstance(values, dict) and set(values) & set(FIELDS) for values in edited):
        return False
    detail = db.get(IncidentDetail, incident.id) if hasattr(db, "get") else None
    death_demo = demographic_total(*((getattr(detail, key, None) for key in ("male_d", "female_d", "children_d")) if detail else ()))
    injury_demo = demographic_total(*((getattr(detail, key, None) for key in ("male_i", "female_i", "children_i")) if detail else ()))
    old = {field: getattr(incident, field) for field in FIELDS}
    incident.total_deaths = derived_total(incident.total_deaths, incident.deaths, death_demo)
    incident.total_injuries = derived_total(incident.total_injuries, incident.injuries, injury_demo)
    new = {field: getattr(incident, field) for field in FIELDS}
    if old == new and not creating:
        return False
    payload: dict[str, Any] = {**new, "reason_code": "created" if creating else reason_code, "raw_message_ids": raw_message_ids or []}
    db.add(IncidentUpdate(incident_id=incident.id, action=UpdateAction.create if creating else UpdateAction.pipeline_merge, old_values=old, new_values=payload))
    return True
