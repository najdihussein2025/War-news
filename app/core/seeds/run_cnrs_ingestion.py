from datetime import datetime, timezone

from sqlalchemy import select

from app.actions.ingest_source_action import ingest_source
from app.core.database import SessionLocal
from app.models.news.source import Source


def main() -> None:
    db = SessionLocal()
    try:
        source = db.scalar(
            select(Source).where(Source.external_id == "cnrs_inspected_posts")
        )
        if source is None:
            raise RuntimeError("Source external_id='cnrs_inspected_posts' was not found.")

        min_message_datetime = datetime.now(timezone.utc).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        summary = ingest_source(
            db=db,
            source_id=source.id,
            min_message_datetime=min_message_datetime,
        )
        print(summary)
    finally:
        db.close()


if __name__ == "__main__":
    main()
