from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.core.database import SessionLocal
from app.api.factories.action_factory import build_filter_relevance_action
from app.llm.dtos import FilterPendingMessagesData


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Step A relevance filtering over pending raw messages."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of pending, unfiltered messages to process.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        action = build_filter_relevance_action(db)
        summary = action.execute(FilterPendingMessagesData(batch_size=args.limit))
    finally:
        db.close()

    print("Relevance filter summary")
    print(f"backend: {settings.relevance_classifier_backend}")
    print(f"ollama_model: {settings.relevance_ollama_model}")
    print(f"limit: {args.limit}")
    print(f"processed: {summary.processed}")
    print(f"relevant: {summary.relevant}")
    print(f"rejected: {summary.rejected}")
    print(f"uncertain: {summary.uncertain}")
    print(f"errored: {summary.errored}")
    print(f"auto_rejected_by_keyword: {summary.auto_rejected_by_keyword}")
    print(f"classifier_calls_made: {summary.classifier_calls_made}")


if __name__ == "__main__":
    main()
