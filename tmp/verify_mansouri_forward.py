import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from uuid import UUID

from app.core.database import SessionLocal
from app.news.models import Incident
from app.news.repositories.incident_repository import IncidentRepository
from app.news.services.dedup.dedup_matching_service import DedupMatchingService

OLD = UUID("fe79c9b1-1a07-4935-8dab-16205d7a0dc9")
NEW = UUID("65204838-de26-4055-9514-6b5b7dbc15ab")


def main() -> None:
    db = SessionLocal()
    try:
        old = db.get(Incident, OLD)
        new = db.get(Incident, NEW)
        assert old is not None and new is not None
        emb = (
            list(new.khabar_embedding)
            if new.khabar_embedding is not None
            else list(old.khabar_embedding)
        )
        existing, score = DedupMatchingService(IncidentRepository(db)).find_best_match(
            village_id=new.village_id,
            condition_id=new.condition_id,
            event_date=new.event_date,
            event_time=new.event_time,
            khabar_embedding=emb,
            exclude_raw_message_id=new.raw_message_id,
        )
        print("existing", None if existing is None else str(existing.id), "score", score)
        print("matched_old", existing is not None and existing.id == OLD)
        assert not (existing is not None and existing.id == OLD)
        print("MANSOURI_FORWARD_OK")
    finally:
        db.close()


if __name__ == "__main__":
    main()
