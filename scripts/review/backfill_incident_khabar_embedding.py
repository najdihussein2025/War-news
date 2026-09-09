#!/usr/bin/env python
"""Populate missing incident embeddings from their linked raw messages."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg2://postgres:secret@localhost:5432/war_news_dev"
)


def _session() -> Session:
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    if "@db:" in url:
        url = url.replace("@db:", "@localhost:")
    return sessionmaker(bind=create_engine(url))()


@dataclass(frozen=True)
class BackfillStats:
    matched: int
    updated: int
    skipped_missing_raw_embedding: int


MATCHED_SQL = text(
    """
    SELECT COUNT(*)
    FROM incidents i
    JOIN raw_messages r ON r.id = i.raw_message_id
    WHERE i.is_deleted = false
      AND i.khabar_embedding IS NULL
      AND r.content_embedding IS NOT NULL
    """
)

SKIPPED_SQL = text(
    """
    SELECT COUNT(*)
    FROM incidents i
    JOIN raw_messages r ON r.id = i.raw_message_id
    WHERE i.is_deleted = false
      AND i.khabar_embedding IS NULL
      AND r.content_embedding IS NULL
    """
)

UPDATE_SQL = text(
    """
    UPDATE incidents AS i
    SET khabar_embedding = r.content_embedding,
        updated_at = NOW()
    FROM raw_messages AS r
    WHERE r.id = i.raw_message_id
      AND i.is_deleted = false
      AND i.khabar_embedding IS NULL
      AND r.content_embedding IS NOT NULL
    """
)


def backfill_incident_embeddings(db: Session) -> BackfillStats:
    matched = int(db.scalar(MATCHED_SQL) or 0)
    skipped = int(db.scalar(SKIPPED_SQL) or 0)
    print(f"Rows matched for update: {matched}")
    print(f"Rows skipped (linked raw message lacks embedding): {skipped}")

    result = db.execute(UPDATE_SQL)
    updated = int(result.rowcount or 0)
    db.commit()
    return BackfillStats(
        matched=matched,
        updated=updated,
        skipped_missing_raw_embedding=skipped,
    )


def main() -> None:
    db = _session()
    try:
        stats = backfill_incident_embeddings(db)
        print(
            "Completed: "
            f"matched={stats.matched} "
            f"updated={stats.updated} "
            "skipped_missing_raw_embedding="
            f"{stats.skipped_missing_raw_embedding}"
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
