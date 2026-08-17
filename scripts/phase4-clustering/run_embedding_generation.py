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
from app.news.repositories.raw_message_repository import RawMessageRepository
from app.news.services.embedding_service import EmbeddingService
from app.news.services.raw_message_embedding_service import (
    RawMessageEmbeddingService,
)

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

    processed = 0
    succeeded = 0
    failed = 0
    last_seen_id = 0

    db = SessionLocal()
    repository = RawMessageRepository(db)
    service = RawMessageEmbeddingService(EmbeddingService())

    try:
        while True:
            raw_message_ids = list(
                db.scalars(
                    select(RawMessage.id)
                    .where(
                        RawMessage.id > last_seen_id,
                        RawMessage.status == MessageStatus.parsed,
                        RawMessage.content_embedding.is_(None),
                    )
                    .order_by(RawMessage.id.asc())
                    .limit(args.batch_size)
                ).all()
            )
            if not raw_message_ids:
                break

            last_seen_id = raw_message_ids[-1]
            batch_succeeded = 0
            batch_failed = 0

            for raw_message_id in raw_message_ids:
                processed += 1
                try:
                    message = db.get(RawMessage, raw_message_id)
                    if message is None:
                        raise ValueError(
                            f"RawMessage id={raw_message_id} not found"
                        )
                    embedding = service.generate(message)
                    repository.save_content_embedding(
                        raw_message_id=raw_message_id,
                        embedding=embedding,
                    )
                    succeeded += 1
                    batch_succeeded += 1
                except Exception as exc:
                    repository.rollback()
                    error_message = str(exc) or f"{type(exc).__name__}: {exc}"
                    logger.error(
                        "raw_message_id=%s failed: %s",
                        raw_message_id,
                        error_message,
                    )
                    failed += 1
                    batch_failed += 1

            logger.info(
                "Batch processed=%s succeeded=%s failed=%s",
                len(raw_message_ids),
                batch_succeeded,
                batch_failed,
            )
    finally:
        db.close()

    print(f"processed={processed} succeeded={succeeded} failed={failed}")


if __name__ == "__main__":
    main()
