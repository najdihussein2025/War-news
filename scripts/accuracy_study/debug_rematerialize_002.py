from app.core.database import SessionLocal
from app.news.models import Incident, MessageStatus, RawMessage
from app.news.repositories.incident_repository import IncidentRepository
from app.news.services.dedup.dedup_matching_service import DedupMatchingService
from app.news.services.materialization.incident_materialization_service import (
    IncidentMaterializationService,
)
from sqlalchemy import select

RAW_ID = 12384

with SessionLocal() as db:
    rm = db.get(RawMessage, RAW_ID)
    print("status", rm.status)
    print("villages", (rm.extraction_result or {}).get("village"))
    matches = (rm.match_result or {}).get("village_matches") or []
    print("match_n", len(matches))
    for m in matches:
        print(
            " ",
            m.get("raw_village_text"),
            m.get("matched_village_id"),
            m.get("village_match_status"),
            m.get("village_role"),
        )
    before = list(
        db.scalars(select(Incident).where(Incident.raw_message_id == RAW_ID)).all()
    )
    print("before", [(i.village_id, i.is_deleted, i.note) for i in before])
    rm.status = MessageStatus.parsed
    db.add(rm)
    db.commit()

    rm = db.get(RawMessage, RAW_ID)
    svc = IncidentMaterializationService(
        db,
        dedup_service=DedupMatchingService(
            incident_repository=IncidentRepository(db)
        ),
    )
    created = svc.materialize(rm)
    print("created", len(created), "stats", svc.stats.__dict__)
    db.commit()
    after = list(
        db.scalars(select(Incident).where(Incident.raw_message_id == RAW_ID)).all()
    )
    print(
        "after",
        [(i.village_id, i.is_deleted, i.note, str(i.id)[:8]) for i in after],
    )
