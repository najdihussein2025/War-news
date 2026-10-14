"""SELECT-only census of suspicious persisted casualty states.

Run in the backend container with PYTHONPATH=/app.  The output is JSON so the
examples can be inspected without changing any database row.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.news.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.news.models.bulletin_casualty_group import BulletinCasualtyGroup
from app.news.models.incident import Incident
from app.news.models.incident_detail import IncidentDetail
from app.news.models.raw_message import RawMessage

IMAGE_CREATED = datetime.fromisoformat("2026-10-14T08:18:57.780702+00:00")
WORDS = ("شهيد", "شهداء", "شهيدان", "استشهاد", "استشهد", "قتيل", "قتلى", "جريح", "جرحى", "جريحان", "إصابة", "إصابات", "مصاب", "مصابين", "ضحية", "ضحايا", "متأثرا بجراحه", "انتشال", "جثث", "جثة")
GENDER_WORDS = ("رجل", "رجال", "امرأة", "نساء", "أنثى", "ذكر", "طفل", "طفلة", "أطفال", "صبي", "فتاة")


def raws(db: Any, incident: Incident) -> list[RawMessage]:
    ids = {incident.raw_message_id} if incident.raw_message_id else set()
    if ids:
        ids.update(db.scalars(select(RawMessage.id).where(RawMessage.duplicate_of_id.in_(ids))))
    return list(db.scalars(select(RawMessage).where(RawMessage.id.in_(ids)))) if ids else []


def extracted_max(rows: list[RawMessage], key: str) -> int | None:
    values: list[int] = []
    for raw in rows:
        block = (raw.extraction_result or {}).get("casualties", {})
        for candidate in (key, key.removeprefix("total_")):
            value = block.get(candidate)
            if isinstance(value, int): values.append(value)
    return max(values) if values else None


def main() -> None:
    db = SessionLocal()
    try:
        incidents = list(db.scalars(select(Incident)))
        details = {str(item.incident_id): item for item in db.scalars(select(IncidentDetail))}
        groups = {item.raw_message_id for item in db.scalars(select(BulletinCasualtyGroup))}
        buckets: dict[str, list[str]] = {str(i): [] for i in range(1, 9)}
        for incident in incidents:
            iid, detail = str(incident.id), details.get(str(incident.id))
            demographic = [getattr(detail, key) for key in ("male_d", "female_d", "children_d")] if detail else []
            demographic_i = [getattr(detail, key) for key in ("male_i", "female_i", "children_i")] if detail else []
            rows, text = raws(db, incident), "\n".join((r.raw_text or "") for r in raws(db, incident))
            if (any(x is not None for x in demographic) and incident.total_deaths is None) or (any(x is not None for x in demographic_i) and incident.total_injuries is None): buckets["1"].append(iid)
            if (incident.total_deaths is not None and sum(x or 0 for x in demographic) > incident.total_deaths) or (incident.total_injuries is not None and sum(x or 0 for x in demographic_i) > incident.total_injuries): buckets["2"].append(iid)
            if ((incident.deaths != incident.total_deaths) or (incident.injuries != incident.total_injuries)) and incident.raw_message_id not in groups: buckets["3"].append(iid)
            if any((getattr(incident, field) or 0) > (extracted_max(rows, field) or 0) for field in ("total_deaths", "total_injuries")): buckets["4"].append(iid)
            body = "\n".join("\n".join((r.raw_text or "").split("\n")[1:]) for r in rows)
            if (incident.total_deaths or incident.total_injuries or incident.deaths or incident.injuries) and not any(word in text for word in WORDS): buckets["5"].append(iid)
            if (incident.total_deaths or incident.total_injuries) and any(word in text.split("\n")[0] for word in WORDS) and not any(word in body for word in WORDS): buckets["6"].append(iid)
            if incident.origin.value == "summary" and (incident.total_deaths or incident.total_injuries or incident.deaths or incident.injuries): buckets["7"].append(iid)
            if detail and (detail.male_d is not None or detail.male_i is not None) and any(word in text for word in ("شهيد", "شهيدان", "شهداء", "جريح", "جرحى")) and not any(word in text for word in GENDER_WORDS): buckets["8"].append(iid)
        result = {}
        for key, ids in buckets.items():
            before = sum(1 for incident in incidents if str(incident.id) in ids and incident.created_at < IMAGE_CREATED)
            result[key] = {"count": len(ids), "before_image": before, "after_image": len(ids) - before, "examples": ids[:5]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
