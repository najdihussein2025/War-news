from app.actions.news import extract_pending_messages
from app.core.database import SessionLocal


def main() -> None:
    db = SessionLocal()
    try:
        summary = extract_pending_messages(db=db, batch_size=10)
        print(summary.model_dump())
    finally:
        db.close()


if __name__ == "__main__":
    main()
