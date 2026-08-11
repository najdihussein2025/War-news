from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.core.news_action_factory import build_ingest_source_action
from app.dtos.news import IngestSourceData
from app.repositories.news import SourceRepository


def main() -> None:
    db = SessionLocal()
    try:
        source = SourceRepository(db).get_active_by_external_id(
            "cnrs_inspected_posts"
        )
        if source is None:
            raise RuntimeError("Source external_id='cnrs_inspected_posts' was not found.")

        min_message_datetime = datetime.now(timezone.utc).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        summary = build_ingest_source_action(db).execute(
            IngestSourceData(
                source_id=source.id,
                min_message_datetime=min_message_datetime,
            )
        )
        print(summary.model_dump())
    finally:
        db.close()


if __name__ == "__main__":
    main()
