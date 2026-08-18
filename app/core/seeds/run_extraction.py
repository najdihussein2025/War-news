import argparse

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.news.services.pipeline_sweep_stages import sweep_extraction


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

    db = SessionLocal()
    try:
        result = sweep_extraction(db, batch_size=args.batch_size)
        print(
            f"processed={result.processed} succeeded={result.succeeded} "
            f"failed={result.failed}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
