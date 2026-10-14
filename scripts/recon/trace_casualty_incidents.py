"""Read-only, incident-centred trace for the five casualty recon cases.

Copy this file to the backend container before running it.  It intentionally
uses ORM SELECT statements only and never invokes pipeline services.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlalchemy import or_, select

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.news.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.news.models.bulletin_casualty_group import BulletinCasualtyGroup
from app.news.models.duplicate_match import DuplicateMatch
from app.news.models.incident import Incident
from app.news.models.incident_detail import IncidentDetail
from app.news.models.incident_update import IncidentUpdate
from app.news.models.incident_verification_flag import IncidentVerificationFlag
from app.news.models.raw_message import RawMessage
from app.news.models.village import Village

CASES = {
    "1-chaqra-page-name": ["4dab80b0-55d2-4f22-a7e1-04df1c4a15da"],
    "2-summary-bulletin": ["af927dd4-7328-4e90-b941-4e395d5287f3"],
    "3-moh-maslakh": ["a876b81c-b70e-4b20-a14a-84c7557d3c78"],
    "4-kfarroumane-11-5": ["711adf5b-5d46-4a5c-8e21-1554c7d975b1"],
    "5-kfarroumane-arabsalim": [
        "cbb16d56-f0f9-456c-9547-39945de9ff96",
        "f88a14c9-3d3e-4a40-ad4e-64705cd0eb6e",
    ],
}
CASUALTY_KEYS = (
    "deaths", "injuries", "total_deaths", "total_injuries", "male_deaths",
    "male_injuries", "female_deaths", "female_injuries", "children_deaths",
    "children_injuries", "male_d", "male_i", "female_d", "female_i",
    "children_d", "children_i", "martyrs", "moh",
)


def value(item: Any) -> Any:
    if isinstance(item, (datetime, date)):
        return item.isoformat()
    if isinstance(item, Enum):
        return item.value
    if hasattr(item, "hex") and item.__class__.__name__ == "UUID":
        return str(item)
    return item if item is None or isinstance(item, (str, int, float, bool, list, dict)) else str(item)


def mapped(model: Any) -> dict[str, Any]:
    return {column.name: value(getattr(model, column.name)) for column in model.__table__.columns}


def casualty_block(raw: RawMessage) -> Any:
    payload = raw.extraction_result or {}
    return payload.get("casualties", payload.get("casualty", payload))


def connected_raws(db: Any, incident: Incident) -> list[RawMessage]:
    """Collect raw rows reachable from ownership, dedup, updates and matches."""
    ids = {incident.raw_message_id} if incident.raw_message_id else set()
    matches = list(db.scalars(select(DuplicateMatch).where(or_(DuplicateMatch.incident_id == incident.id, DuplicateMatch.matched_incident_id == incident.id))))
    ids.update(match.raw_message_id for match in matches if match.raw_message_id)
    # Audit JSON is schema-less; retain any conventional raw-message provenance.
    for update in db.scalars(select(IncidentUpdate).where(IncidentUpdate.incident_id == incident.id)):
        for payload in (update.old_values or {}, update.new_values or {}):
            for key in ("raw_message_id", "source_raw_message_id", "incoming_raw_message_id"):
                if isinstance(payload.get(key), int):
                    ids.add(payload[key])
    # Closure over both directions permits a pre-extraction duplicate chain.
    changed = True
    while changed:
        changed = False
        for raw in db.scalars(select(RawMessage).where(or_(RawMessage.id.in_(ids), RawMessage.duplicate_of_id.in_(ids)))):
            if raw.id not in ids:
                ids.add(raw.id)
                changed = True
    return list(db.scalars(select(RawMessage).where(RawMessage.id.in_(ids)).order_by(RawMessage.received_at))) if ids else []


def compact_raw(raw: RawMessage) -> dict[str, Any]:
    return {
        "id": raw.id, "duplicate_of_id": raw.duplicate_of_id, "source_id": raw.source_id,
        "received_at": value(raw.received_at), "text_first_300": (raw.raw_text or "")[:300],
        "casualties": casualty_block(raw), "match_result": raw.match_result,
    }


def trace(db: Any, incident_id: str) -> dict[str, Any]:
    incident = db.scalar(select(Incident).where(Incident.id == incident_id))
    if incident is None:
        return {"incident_id": incident_id, "missing": True}
    village = db.scalar(select(Village).where(Village.id == incident.village_id)) if incident.village_id else None
    updates = list(db.scalars(select(IncidentUpdate).where(IncidentUpdate.incident_id == incident.id).order_by(IncidentUpdate.created_at)))
    rows = mapped(incident)
    incident_view = {key: rows.get(key) for key in set(CASUALTY_KEYS) | {
        "id", "raw_message_id", "village_id", "created_at", "updated_at", "casualty_status",
        "casualty_status_evidence", "casualty_status_remaining_total", "verification_reason", "note_extra",
    }}
    incident_view["village"] = mapped(village) if village else None
    timeline = []
    for update in updates:
        old, new = update.old_values or {}, update.new_values or {}
        changes = {key: {"old": old.get(key), "new": new.get(key)} for key in CASUALTY_KEYS if key in old or key in new}
        if changes:
            timeline.append({"at": value(update.created_at), "action": value(update.action), "changes": changes,
                             "provenance": {key: new.get(key) for key in new if "raw" in key or "scope" in key or "proven" in key}})
    return {
        "incident": incident_view,
        "incident_detail": mapped(db.scalar(select(IncidentDetail).where(IncidentDetail.incident_id == incident.id))) if db.scalar(select(IncidentDetail).where(IncidentDetail.incident_id == incident.id)) else None,
        "raw_messages": [compact_raw(raw) for raw in connected_raws(db, incident)],
        "incident_updates": [mapped(update) for update in updates],
        "casualty_timeline_from_audit": timeline,
        "duplicate_matches": [mapped(row) for row in db.scalars(select(DuplicateMatch).where(or_(DuplicateMatch.incident_id == incident.id, DuplicateMatch.matched_incident_id == incident.id)))],
        "bulletin_casualty_groups": [mapped(row) for row in db.scalars(select(BulletinCasualtyGroup).where(BulletinCasualtyGroup.raw_message_id == incident.raw_message_id))],
        "verification_flags": [mapped(row) for row in db.scalars(select(IncidentVerificationFlag).where(IncidentVerificationFlag.incident_id == incident.id))],
    }


def main() -> None:
    db = SessionLocal()
    try:
        for case, ids in CASES.items():
            print(json.dumps({"case": case, "traces": [trace(db, item) for item in ids]}, ensure_ascii=False, indent=2, default=value))
    finally:
        db.close()


if __name__ == "__main__":
    main()
