#!/usr/bin/env python
"""Regenerate embeddings for raw messages matching new outlet boilerplate."""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.logs import models as _log_models  # noqa: F401
from app.news.models import RawMessage
from app.news.repositories.raw_message_repository import RawMessageRepository
from app.news.services.clustering.embedding_service import EmbeddingService
from app.news.services.clustering.raw_message_embedding_service import (
    BOILERPLATE_PATTERNS,
    RawMessageEmbeddingService,
)
from app.sources import models as _source_models  # noqa: F401

DEFAULT_DATABASE_URL = "postgresql+psycopg2://postgres:secret@localhost:5432/war_news_dev"
NEW_PATTERN_LABELS = {
    "NNA attribution",
    "Al Mayadeen correspondent attribution",
    "Lebanon24 attribution",
    "Lebanon24 trailing noise",
}
NEW_PATTERNS = tuple(
    pattern
    for label, pattern in BOILERPLATE_PATTERNS
    if label in NEW_PATTERN_LABELS
)


def _session() -> Session:
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    if "@db:" in url:
        url = url.replace("@db:", "@localhost:")
    return sessionmaker(bind=create_engine(url))()


def _matches_new_pattern(raw_text: str | None) -> bool:
    text = raw_text or ""
    return any(pattern.search(text) for pattern in NEW_PATTERNS)


def fetch_affected_messages(db: Session) -> list[RawMessage]:
    candidates = db.scalars(
        select(RawMessage)
        .where(
            RawMessage.raw_text.is_not(None),
            or_(
                RawMessage.raw_text.ilike("%الوكالة الوطنية%"),
                RawMessage.raw_text.ilike("%الميادين%"),
                RawMessage.raw_text.ilike("%لبنان24%"),
                RawMessage.raw_text.ilike("%لبنان 24%"),
                RawMessage.raw_text.ilike("%lebanon24%"),
            ),
        )
        .order_by(RawMessage.id.asc())
    ).all()
    return [message for message in candidates if _matches_new_pattern(message.raw_text)]


def main() -> None:
    db = _session()
    try:
        messages = fetch_affected_messages(db)
        print(f"Affected raw messages: {len(messages)}")

        repository = RawMessageRepository(db)
        service = RawMessageEmbeddingService(EmbeddingService())
        processed = 0
        succeeded = 0
        failed = 0

        for message in messages:
            processed += 1
            try:
                embedding = service.generate(message)
                repository.save_content_embedding(
                    raw_message_id=message.id,
                    embedding=embedding,
                )
                succeeded += 1
            except Exception as exc:
                repository.rollback()
                failed += 1
                print(f"raw_message_id={message.id} failed: {type(exc).__name__}: {exc}")

            if processed % 25 == 0 or processed == len(messages):
                print(
                    f"Progress: processed={processed} "
                    f"succeeded={succeeded} failed={failed}"
                )

        print(
            f"Completed: matched={len(messages)} processed={processed} "
            f"updated={succeeded} failed={failed}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
