"""Read-only trace for the five casualty recon cases.

Run only in the backend container:
    docker compose exec backend python scripts/recon/trace_casualty_cases.py

The script deliberately uses ORM SELECT statements only.  It does not call a
pipeline service, commit, flush, or modify any model object.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlalchemy import or_, select

# Register all relationship targets before ORM queries.  Importing individual
# model modules is insufficient because several relationships are string-based.
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


CASES = {
    "1-chaqra-page-name": "صفحة الإعلامي الشهيد علي شعيب",
    "2-summary-bulletin": "ملخص الاعتداءات التي طالت بلدات و قرى جنوبية",
    "3-moh-maslakh": "مركز عمليات طوارئ الصحة",
    "4-kfarroumane-11-5": "11 شهيدًا و5 جرحى في غارات ليلًا على مبنى وسيارة في كفررمان",
    "5-kfarroumane-5-injured": "إصابة 5 أشخاص في قصف مدفعي إسرائيلي استهدف منزلاً في بلدة كفررمان",
}


def value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "hex") and value.__class__.__name__ == "UUID":
        return str(value)
    # JSONB values are already JSON-native.  This fallback is for database
    # adapters' UUID/Decimal/vector wrappers and must not return itself.
    return str(value)


def row(model: Any) -> dict[str, Any]:
    """Serialize mapped columns only; relationships are intentionally not loaded."""
    return {column.name: value(getattr(model, column.name)) for column in model.__table__.columns}


def trace_message(db: Any, message: RawMessage) -> dict[str, Any]:
    incidents = list(db.scalars(select(Incident).where(Incident.raw_message_id == message.id)))
    # A pre-extraction duplicate may point at a raw row whose incidents own
    # the displayed values, so include both directions of that link.
    linked_raws = list(
        db.scalars(
            select(RawMessage).where(
                or_(RawMessage.id == message.duplicate_of_id, RawMessage.duplicate_of_id == message.id)
            )
        )
    ) if message.duplicate_of_id is not None else list(
        db.scalars(select(RawMessage).where(RawMessage.duplicate_of_id == message.id))
    )
    all_raw_ids = {message.id, *(item.id for item in linked_raws)}
    incidents.extend(
        db.scalars(select(Incident).where(Incident.raw_message_id.in_(all_raw_ids))).all()
    )
    unique_incidents = {str(item.id): item for item in incidents}.values()
    result: dict[str, Any] = {
        "raw_message": row(message),
        "stored_stage_outputs": {
            "filter_result": message.filter_result,
            "extraction_result": message.extraction_result,
            "match_result": message.match_result,
            "cnrs_classification": message.cnrs_classification,
            "duplicate_of_id": message.duplicate_of_id,
        },
        "bulletin_casualty_groups": [
            row(item)
            for item in db.scalars(
                select(BulletinCasualtyGroup).where(BulletinCasualtyGroup.raw_message_id == message.id)
            )
        ],
        "linked_raw_messages": [row(item) for item in linked_raws],
        "incidents": [],
    }
    for incident in unique_incidents:
        incident_id = incident.id
        result["incidents"].append({
            "incident": row(incident),
            "detail": (lambda x: row(x) if x else None)(db.scalar(select(IncidentDetail).where(IncidentDetail.incident_id == incident_id))),
            "updates": [row(x) for x in db.scalars(select(IncidentUpdate).where(IncidentUpdate.incident_id == incident_id))],
            "duplicate_matches": [row(x) for x in db.scalars(select(DuplicateMatch).where(or_(DuplicateMatch.incident_id == str(incident_id), DuplicateMatch.matched_incident_id == str(incident_id))))],
            "verification_flags": [row(x) for x in db.scalars(select(IncidentVerificationFlag).where(IncidentVerificationFlag.incident_id == incident_id))],
            "other_raw_messages_on_incident": [row(x) for x in db.scalars(select(RawMessage).where(RawMessage.id != message.id, RawMessage.id == incident.raw_message_id))],
        })
    return result


def main() -> None:
    db = SessionLocal()
    try:
        for name, snippet in CASES.items():
            messages = list(db.scalars(select(RawMessage).where(RawMessage.raw_text.ilike(f"%{snippet}%")).order_by(RawMessage.received_at)))
            print(json.dumps({"case": name, "snippet": snippet, "match_count": len(messages), "matches": [trace_message(db, item) for item in messages]}, ensure_ascii=False, indent=2, default=value))
    finally:
        db.close()


if __name__ == "__main__":
    main()
