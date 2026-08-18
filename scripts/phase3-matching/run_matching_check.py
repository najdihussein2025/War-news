from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.news.services.pipeline_sweep_stages import sweep_matching


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Match extracted villages and conditions for parsed messages."
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--rematch",
        action="store_true",
        help="Include messages that already have a match_result.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be at least 1")

    db = SessionLocal()
    try:
        result = sweep_matching(
            db,
            batch_size=args.limit,
            rematch=args.rematch,
        )
        print(
            f"processed={result.processed} succeeded={result.succeeded} "
            f"failed={result.failed}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
