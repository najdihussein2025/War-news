import logging
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.models.news import RawMessage

BATCH_SIZE = 500

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    total_updated = 0
    total_missing_payload_fields = 0
    last_seen_id = 0

    while True:
        with SessionLocal() as db:
            rows = db.scalars(
                select(RawMessage)
                .where(
                    RawMessage.id > last_seen_id,
                    (RawMessage.source_platform.is_(None))
                    | (RawMessage.source_name.is_(None))
                )
                .order_by(RawMessage.id.asc())
                .limit(BATCH_SIZE)
            ).all()

            if not rows:
                break

            last_seen_id = rows[-1].id
            batch_updated = 0
            batch_missing_payload_fields = 0

            for message in rows:
                if not isinstance(message.raw_payload, dict):
                    batch_missing_payload_fields += 1
                    continue

                source_platform = message.raw_payload.get("source_platform")
                source_name = message.raw_payload.get("source_name")

                if not source_platform or not source_name:
                    batch_missing_payload_fields += 1
                    continue

                message.source_platform = source_platform
                message.source_name = source_name
                db.add(message)
                batch_updated += 1

            db.commit()
            total_updated += batch_updated
            total_missing_payload_fields += batch_missing_payload_fields

            logger.info(
                "Batch processed=%s updated=%s missing_payload_fields=%s",
                len(rows),
                batch_updated,
                batch_missing_payload_fields,
            )

    logger.info("Backfill complete.")
    logger.info("Rows updated: %s", total_updated)
    logger.info("Rows skipped with missing payload fields: %s", total_missing_payload_fields)


if __name__ == "__main__":
    main()
