from app.core.database import SessionLocal
from app.api.factories.action_factory import build_extract_incidents_action
from app.llm.dtos import ExtractPendingMessagesData


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
