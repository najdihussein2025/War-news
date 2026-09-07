import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from unittest.mock import MagicMock
from uuid import UUID

from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.llm.dtos import (
    ExtractionCasualties,
    ExtractionCategory,
    ExtractionCategoryKey,
    ExtractionVehicleDetails,
)
from app.news.models import Incident, IncidentDetail, RawMessage
from app.news.repositories.incident_repository import IncidentRepository
from app.news.services.dedup.dedup_matching_service import DedupMatchingService
from app.news.services.extraction.tier2_detail_fill_service import Tier2DetailFillService

RAW_ID = 4389
MANSOURI_OLD = UUID("fe79c9b1-1a07-4935-8dab-16205d7a0dc9")
MANSOURI_NEW = UUID("65204838-de26-4055-9514-6b5b7dbc15ab")


def main() -> None:
    db = SessionLocal()
    try:
        raw = db.get(RawMessage, RAW_ID)
        incident = db.scalar(
            select(Incident).where(
                Incident.raw_message_id == RAW_ID,
                Incident.is_deleted.is_(False),
            )
        )
        assert raw is not None and incident is not None
        incident.details_pending = True
        db.add(incident)
        db.commit()

        tier2_categories = {
            ExtractionCategoryKey.emergency_civil_defense: ExtractionCategory(
                name="كشافة الرسالة الإسلامية",
                casualties=ExtractionCasualties(deaths=1, injuries=2),
                vehicles=ExtractionVehicleDetails(car=True),
            )
        }
        service = Tier2DetailFillService(
            db,
            classifier=MagicMock(),
            dedup_service=None,
        )
        updated = service.apply_tier2_result_for_raw_message(
            RAW_ID, tier2_categories=tier2_categories
        )
        print("UPDATED", updated)

        detail = db.scalar(
            select(IncidentDetail).where(IncidentDetail.incident_id == incident.id)
        )
        assert detail is not None
        print(
            "AFTER",
            {
                "emer": detail.emer,
                "emer_rela": detail.emer_rela,
                "e_cars": detail.e_cars,
                "car_nbr": detail.car_nbr,
                "emer_d": detail.emer_d,
                "emer_i": detail.emer_i,
            },
        )
        assert detail.emer is True
        assert detail.emer_rela == "كشافة الرسالة الإسلامية"
        assert detail.e_cars is True
        assert detail.car_nbr == 1
        assert detail.emer_d == 1
        assert detail.emer_i == 2
        print("KFAR_ROUMMANE_OK")

        old = db.get(Incident, MANSOURI_OLD)
        new = db.get(Incident, MANSOURI_NEW)
        assert old is not None and new is not None
        dedup = DedupMatchingService(IncidentRepository(db))
        existing, score = dedup.find_best_match(
            village_id=old.village_id,
            condition_id=old.condition_id,
            event_date=new.event_date,
            event_time=new.event_time,
            khabar_embedding=list(old.khabar_embedding or new.khabar_embedding),
            exclude_raw_message_id=new.raw_message_id,
        )
        matched_old = existing is not None and existing.id == old.id
        print(
            "MANSOURI find_best_match existing=",
            None if existing is None else str(existing.id),
            "score=",
            score,
            "matched_old=",
            matched_old,
        )
        assert not matched_old
        print("MANSOURI_OK")

        rows = db.execute(
            text(
                """
                SELECT id, status, similarity_score, created_at
                FROM duplicate_matches
                WHERE (incident_id = :a AND matched_incident_id = :b)
                   OR (incident_id = :b AND matched_incident_id = :a)
                ORDER BY created_at
                """
            ),
            {"a": str(MANSOURI_OLD), "b": str(MANSOURI_NEW)},
        ).all()
        print("MANSOURI_HISTORICAL_MATCH_ROWS", len(rows))
        for row in rows:
            print(" ", row)
    finally:
        db.close()


if __name__ == "__main__":
    main()
