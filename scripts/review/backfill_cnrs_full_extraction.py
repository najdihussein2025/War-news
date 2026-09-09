#!/usr/bin/env python
"""Review or requeue legacy minimal CNRS extractions.

Dry-run is the default. ``--apply`` soft-deletes only safe, automatically
materialized incidents and resets their raw messages to the extraction stage.
Rows involved in merge/duplicate history are reported but never changed.

Usage:
  python scripts/review/backfill_cnrs_full_extraction.py
  python scripts/review/backfill_cnrs_full_extraction.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg2://postgres:secret@localhost:5432/war_news_dev"
)


@dataclass(frozen=True)
class BackfillCandidate:
    raw_message_id: int
    source_name: str | None
    location: str | None
    active_incidents: int
    has_merge_or_duplicate_history: bool

    @property
    def safe_to_requeue(self) -> bool:
        return not self.has_merge_or_duplicate_history


def _session() -> Session:
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    if "@db:" in url:
        url = url.replace("@db:", "@localhost:")
    return sessionmaker(bind=create_engine(url))()


def fetch_candidates(db: Session, limit: int | None) -> list[BackfillCandidate]:
    limit_clause = "LIMIT :limit" if limit is not None else ""
    rows = db.execute(
        text(
            f"""
            SELECT
              rm.id AS raw_message_id,
              rm.source_name,
              rm.cnrs_classification->>'location' AS location,
              COUNT(DISTINCT i.id) FILTER (WHERE i.is_deleted = false)
                AS active_incidents,
              (
                COUNT(DISTINCT iu.id) > 0
                OR COUNT(DISTINCT dm.id) > 0
              ) AS has_merge_or_duplicate_history
            FROM raw_messages rm
            LEFT JOIN incidents i
              ON i.raw_message_id = rm.id
            LEFT JOIN incident_updates iu
              ON iu.incident_id = i.id
            LEFT JOIN duplicate_matches dm
              ON dm.incident_id = i.id OR dm.matched_incident_id = i.id
            WHERE rm.extraction_result->>'model' = 'cnrs_provided'
              AND rm.cnrs_classification->>'include' = 'true'
            GROUP BY rm.id, rm.source_name, rm.cnrs_classification
            ORDER BY rm.id
            {limit_clause}
            """
        ),
        {"limit": limit} if limit is not None else {},
    ).mappings()
    return [
        BackfillCandidate(
            raw_message_id=row["raw_message_id"],
            source_name=row["source_name"],
            location=row["location"],
            active_incidents=int(row["active_incidents"] or 0),
            has_merge_or_duplicate_history=bool(
                row["has_merge_or_duplicate_history"]
            ),
        )
        for row in rows
    ]


def print_review(candidates: list[BackfillCandidate], examples: int) -> None:
    safe = [item for item in candidates if item.safe_to_requeue]
    unsafe = [item for item in candidates if not item.safe_to_requeue]
    incident_count = sum(item.active_incidents for item in safe)
    print("=== CNRS full-extraction backfill (dry run) ===")
    print(f"legacy raw messages found: {len(candidates)}")
    print(f"safe raw messages to requeue: {len(safe)}")
    print(f"active incidents to replace: {incident_count}")
    print(f"skipped due to merge/duplicate history: {len(unsafe)}")
    for item in candidates[:examples]:
        status = "safe" if item.safe_to_requeue else "skip-history"
        print(
            f"  raw={item.raw_message_id} status={status} "
            f"incidents={item.active_incidents} "
            f"source={item.source_name!r} location={item.location!r}"
        )


def apply_backfill(db: Session, candidates: list[BackfillCandidate]) -> int:
    safe_ids = [
        item.raw_message_id for item in candidates if item.safe_to_requeue
    ]
    if not safe_ids:
        return 0

    db.execute(
        text(
            """
            UPDATE incidents
            SET is_deleted = true,
                duplicate_flag = false,
                verification_reason = NULL
            WHERE raw_message_id = ANY(:raw_ids)
              AND is_deleted = false
            """
        ),
        {"raw_ids": safe_ids},
    )
    db.execute(
        text(
            """
            UPDATE raw_messages
            SET extraction_result = NULL,
                match_result = NULL,
                duplicate_of_id = NULL,
                status = 'parsed',
                error_message = NULL,
                extraction_retry_count = 0,
                match_retry_count = 0,
                extracted_at = NULL,
                matched_at = NULL,
                fast_path_completed_at = NULL,
                tier2_completed_at = NULL,
                materialized_at = NULL,
                processing_claim_stage = NULL,
                processing_claimed_at = NULL,
                processing_claimed_by = NULL
            WHERE id = ANY(:raw_ids)
            """
        ),
        {"raw_ids": safe_ids},
    )
    db.commit()
    return len(safe_ids)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Review or requeue legacy minimal CNRS extractions."
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--examples", type=int, default=20)
    args = parser.parse_args()

    with _session() as db:
        candidates = fetch_candidates(db, args.limit)
        print_review(candidates, max(args.examples, 0))
        if not args.apply:
            print("\nDry run only. Pass --apply to requeue safe records.")
            return 0
        changed = apply_backfill(db, candidates)

    print(f"\nRequeued raw messages: {changed}")
    print("Pipeline workers will perform full extraction and rematerialization.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
