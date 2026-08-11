from app.actions.news import filter_pending_messages
from app.core.database import SessionLocal


def main() -> None:
    db = SessionLocal()
    try:
        summary = filter_pending_messages(db=db)
        print("Relevance filter summary")
        print(f"processed: {summary.processed}")
        print(f"relevant: {summary.relevant}")
        print(f"rejected: {summary.rejected}")
        print(f"errored: {summary.errored}")
        print(f"auto_rejected_by_keyword: {summary.auto_rejected_by_keyword}")
        print(f"gemini_calls_made: {summary.gemini_calls_made}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
