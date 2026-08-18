from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.llm.dtos import ExtractPendingMessagesData
from app.news.services.pipeline_sweep_stages import sweep_embedding_generation

DEFAULT_BATCH_SIZE = ExtractPendingMessagesData().batch_size

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate embeddings for parsed raw messages."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Number of raw messages to load per batch.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be at least 1")

    db = SessionLocal()
    try:
        result = sweep_embedding_generation(db, batch_size=args.batch_size)
        print(
            f"processed={result.processed} succeeded={result.succeeded} "
            f"failed={result.failed}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
