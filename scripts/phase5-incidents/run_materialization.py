from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.llm.dtos import ExtractPendingMessagesData
from app.news.models import MessageStatus, RawMessage
from app.news.services.incident_materialization_service import (
    IncidentMaterializationService,
)

DEFAULT_BATCH_SIZE = ExtractPendingMessagesData().batch_size

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize representative raw messages as incidents."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Number of representative raw messages to load per batch.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be at least 1")

    processed = 0
    failed = 0
    last_seen_id = 0

    db = SessionLocal()
    service = IncidentMaterializationService(db)

    try:
        while True:
            batch = list(
                db.scalars(
                    select(RawMessage)
                    .where(
                        RawMessage.id > last_seen_id,
                        RawMessage.status == MessageStatus.parsed,
                        RawMessage.duplicate_of_id.is_(None),
                        RawMessage.match_result.is_not(None),
                    )
                    .order_by(RawMessage.id.asc())
                    .limit(args.batch_size)
                ).all()
            )
            if not batch:
                break

            last_seen_id = batch[-1].id
            batch_inserted_before = service.stats.inserted
            batch_ineligible_before = service.stats.skipped_ineligible
            batch_duplicate_before = service.stats.skipped_duplicate_hash
            batch_failed = 0

            for representative in batch:
                processed += 1
                try:
                    service.materialize(representative)
                except Exception as exc:
                    db.rollback()
                    error_message = str(exc) or f"{type(exc).__name__}: {exc}"
                    failed += 1
                    batch_failed += 1
                    logger.error(
                        "raw_message_id=%s materialization failed: %s",
                        representative.id,
                        error_message,
                    )

            logger.info(
                "Batch processed=%s inserted=%s skipped_ineligible=%s "
                "skipped_duplicate_hash=%s failed=%s",
                len(batch),
                service.stats.inserted - batch_inserted_before,
                service.stats.skipped_ineligible - batch_ineligible_before,
                service.stats.skipped_duplicate_hash - batch_duplicate_before,
                batch_failed,
            )
    finally:
        db.close()

    print(
        f"processed={processed} inserted={service.stats.inserted} "
        f"skipped_ineligible={service.stats.skipped_ineligible} "
        f"skipped_duplicate_hash={service.stats.skipped_duplicate_hash} "
        f"failed={failed}"
    )


if __name__ == "__main__":
    main()
