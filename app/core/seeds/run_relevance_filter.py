from app.actions.news import filter_pending_messages
from app.core.database import SessionLocal


def main() -> None:
    db = SessionLocal()
    try:
        summary = filter_pending_messages(db=db, batch_size=20)
        print(summary.model_dump())
    finally:
        db.close()


if __name__ == "__main__":
    main()
