from app.core.database import SessionLocal
from app.core.news_action_factory import build_extract_incidents_action
from app.dtos.news import ExtractPendingMessagesData


def main() -> None:
    db = SessionLocal()
    try:
        summary = build_extract_incidents_action(db).execute(
            ExtractPendingMessagesData(batch_size=10)
        )
        print(summary.model_dump())
    finally:
        db.close()


if __name__ == "__main__":
    main()
