#!/usr/bin/env python
"""Re-apply the current classification rules to stored air-violation rows.

Counting (breaches) is computed at read time, so existing rows already follow
the new CNRS counting rules. What can still be stale is a row's condition: a
drone stored as a helicopter, a helicopter stored without a helicopter word, or
a spy balloon stored as something else. This re-runs ``classify_condition`` on
each row's original text (raw message text, else the stored khabar).

Only ``condition_id`` is changed. No row is deleted. A row whose label cannot be
confirmed (a helicopter row with no helicopter word and no other air reading) is
listed for human review and left alone. ``--apply`` also bumps the air-violation
cache version so cards and lists recompute; ``--bump-cache-only`` does just that.

Dry-run is the default.

Usage:
  python scripts/reclassify_air_violations.py
  python scripts/reclassify_air_violations.py --apply
  python scripts/reclassify_air_violations.py --bump-cache-only
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import app.accounts.models  # noqa: F401,E402
import app.logs.models  # noqa: E402,F401
import app.sources.models  # noqa: E402,F401
import app.news.services  # noqa: E402,F401  (import order avoids a pre-existing llm_knowledge cycle)
from app.core.cache import increment  # noqa: E402
from app.news.constants.air_violation_conditions import (  # noqa: E402
    AIR_VIOLATION_CONDITION_IDS,
    AIR_VIOLATION_HELICOPTER_CONDITION_ID,
)
from app.news.models import AirViolation, RawMessage  # noqa: E402
from app.sources.services.red_alert_collector import (  # noqa: E402
    classify_condition,
    has_helicopter_keyword,
)

CACHE_KEY = "air-violations:cache-version"
BATCH_SIZE = 200


@dataclass
class Summary:
    scanned: int = 0
    unchanged: int = 0
    changed: Counter = field(default_factory=Counter)
    needs_review: list[int] = field(default_factory=list)
    processed: int = 0
    succeeded: int = 0
    failed: int = 0


def target_condition(current: int, text: str) -> int | None:
    """The condition the row should have, or ``None`` when it cannot be confirmed."""
    classified = classify_condition(text)
    if classified in AIR_VIOLATION_CONDITION_IDS:
        return classified
    if current == AIR_VIOLATION_HELICOPTER_CONDITION_ID and not has_helicopter_keyword(text):
        return None
    return current


def run(db, *, apply: bool) -> Summary:
    summary = Summary()
    rows = db.execute(
        select(AirViolation, RawMessage.raw_text)
        .outerjoin(RawMessage, RawMessage.id == AirViolation.raw_message_id)
        .order_by(AirViolation.id)
    ).all()
    updates: list[tuple[AirViolation, int]] = []
    for record, raw_text in rows:
        summary.scanned += 1
        target = target_condition(record.condition_id, raw_text or record.khabar or "")
        if target is None:
            summary.needs_review.append(record.id)
        elif target == record.condition_id:
            summary.unchanged += 1
        else:
            summary.changed[(record.condition_id, target)] += 1
            updates.append((record, target))
    if not apply:
        return summary
    for start in range(0, len(updates), BATCH_SIZE):
        batch = updates[start:start + BATCH_SIZE]
        summary.processed += len(batch)
        try:
            for record, target in batch:
                record.condition_id = target
            db.commit()
            summary.succeeded += len(batch)
        except Exception:  # noqa: BLE001
            db.rollback()
            summary.failed += len(batch)
    increment(CACHE_KEY)
    return summary


def print_summary(summary: Summary, *, apply: bool) -> None:
    print(f"=== reclassify air violations ({'apply' if apply else 'dry run'}) ===")
    print(f"scanned: {summary.scanned}  unchanged: {summary.unchanged}")
    for (old, new), count in sorted(summary.changed.items()):
        print(f"  {old} -> {new}: {count}")
    print(f"needs review (label unconfirmed, left alone): {len(summary.needs_review)}")
    print(f"  ids: {summary.needs_review[:50]}")
    if apply:
        print(f"processed: {summary.processed}  succeeded: {summary.succeeded}  failed: {summary.failed}")
    else:
        print("\nDry run only - no writes. Re-run with --apply.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--bump-cache-only", action="store_true")
    args = parser.parse_args(argv)
    if args.bump_cache_only:
        print(f"cache version: {increment(CACHE_KEY)}")
        return
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        print_summary(run(db, apply=args.apply), apply=args.apply)
    finally:
        db.close()


if __name__ == "__main__":
    main()
