from __future__ import annotations

import logging
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.news.models import AirViolation, Incident

AIR_VIOLATION_CONDITION_IDS = (35, 36, 38)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    db = SessionLocal()
    try:
        incidents = list(
            db.scalars(
                select(Incident).where(
                    Incident.condition_id.in_(AIR_VIOLATION_CONDITION_IDS),
                    Incident.is_deleted.is_(False),
                )
            ).all()
        )

        if not incidents:
            print("No live incidents found for condition_id IN (35, 36, 38).")
            return

        deleted_ids: list[str] = []
        missing_air_violation_raw_message_ids: list[int] = []

        for incident in incidents:
            air_violation_id = db.scalar(
                select(AirViolation.id).where(
                    AirViolation.raw_message_id == incident.raw_message_id
                )
            )
            if air_violation_id is None:
                missing_air_violation_raw_message_ids.append(incident.raw_message_id)

            incident.is_deleted = True
            db.add(incident)
            deleted_ids.append(str(incident.id))
            logger.info(
                "Soft-deleted incident id=%s raw_message_id=%s condition_id=%s "
                "air_violation_exists=%s",
                incident.id,
                incident.raw_message_id,
                incident.condition_id,
                air_violation_id is not None,
            )

        db.commit()

        print(
            f"incidents_soft_deleted={len(deleted_ids)} "
            f"incident_ids={deleted_ids} "
            f"missing_air_violation_count={len(missing_air_violation_raw_message_ids)} "
            f"missing_air_violation_raw_message_ids={missing_air_violation_raw_message_ids}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
