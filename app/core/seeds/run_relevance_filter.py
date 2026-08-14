from app.core.database import SessionLocal
from app.api.factories.action_factory import build_filter_relevance_action
from app.llm.dtos import FilterPendingMessagesData


def main() -> None:
    db = SessionLocal()
    try:
        summary = build_filter_relevance_action(db).execute(
            FilterPendingMessagesData()
        )
        print("Relevance filter summary")
        print(f"processed: {summary.processed}")
        print(f"relevant: {summary.relevant}")
        print(f"rejected: {summary.rejected}")
        print(f"uncertain: {summary.uncertain}")
        print(f"errored: {summary.errored}")
        print(f"auto_rejected_by_keyword: {summary.auto_rejected_by_keyword}")
        print(f"classifier_calls_made: {summary.classifier_calls_made}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
