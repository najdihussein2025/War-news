import argparse

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.api.factories.action_factory import build_extract_incidents_action
from app.llm.dtos import ExtractPendingMessagesData


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract incidents from parsed raw messages."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Number of raw messages to process per batch.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be at least 1")

    processed = 0
    succeeded = 0
    failed = 0

    db = SessionLocal()
    try:
        action = build_extract_incidents_action(db)
        while True:
            summary = action.execute(
                ExtractPendingMessagesData(batch_size=args.batch_size)
            )
            if summary.processed == 0:
                break

            processed += summary.processed
            succeeded += summary.extracted
            failed += summary.errored
            print(
                f"Batch processed={summary.processed} "
                f"succeeded={summary.extracted} failed={summary.errored}"
            )
    finally:
        db.close()

    print(f"processed={processed} succeeded={succeeded} failed={failed}")


if __name__ == "__main__":
    main()
