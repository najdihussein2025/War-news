#!/usr/bin/env python
"""Backfill active non-duplicate incidents to ``auto_processed``.

Verification is now reserved for possible duplicates. This script finds active
incidents still marked ``needs_verification`` without a duplicate flag and
clears their obsolete review state.

Dry-run is the default. Use ``--apply`` only after reviewing the output.

Usage:
  python scripts/review/backfill_verification_duplicate_only.py
  python scripts/review/backfill_verification_duplicate_only.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.news.models import IncidentUpdate, UpdateAction

DEFAULT_DATABASE_URL = "postgresql+psycopg2://postgres:secret@localhost:5432/war_news_dev"
SYSTEM_RESOLVER_USERNAME = "system.verification_duplicate_only_backfill"
SYSTEM_RESOLVER_FULL_NAME = "System · Verification Duplicate-Only Backfill"


def _session() -> Session:
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    if "@db:" in url:
        url = url.replace("@db:", "@localhost:")
    return sessionmaker(bind=create_engine(url))()


@dataclass(frozen=True)
class BackfillPlan:
    incident_id: UUID
    village: str | None
    condition: str | None
    verification_reason: str | None


def _reason_bucket(reason: str | None) -> str:
    normalized = (reason or "").lower()
    for bucket in ("relevance", "casualty", "confidence", "village", "condition"):
        if bucket in normalized:
            return bucket
    return "other" if normalized else "(none)"


def fetch_plans(db: Session) -> list[BackfillPlan]:
    rows = db.execute(
        text(
            """
            SELECT
              i.id AS incident_id,
              COALESCE(v.ref_name_en, v.cad_name) AS village,
              c.action_en AS condition,
              i.verification_reason
            FROM incidents i
            LEFT JOIN villages v ON v.id = i.village_id
            LEFT JOIN conditions c ON c.id = i.condition_id
            WHERE i.is_deleted = false
              AND i.verification_status = 'needs_verification'
              AND i.duplicate_flag = false
            ORDER BY i.created_at DESC
            """
        )
    ).mappings().all()
    return [
        BackfillPlan(
            incident_id=row["incident_id"],
            village=row["village"],
            condition=row["condition"],
            verification_reason=row["verification_reason"],
        )
        for row in rows
    ]


def print_dry_run(plans: list[BackfillPlan], example_count: int) -> None:
    counts = Counter(_reason_bucket(plan.verification_reason) for plan in plans)
    print("=== verification duplicate-only backfill (dry run) ===")
    print(f"active incidents that would change: {len(plans)}")
    print("\nGrouped by current verification_reason:")
    for bucket in ("relevance", "casualty", "confidence", "village", "condition", "other", "(none)"):
        if counts[bucket]:
            print(f"  {bucket}: {counts[bucket]}")

    print(f"\nExamples (up to {example_count}):")
    for plan in plans[:example_count]:
        print(
            f"  {plan.incident_id}  {plan.village!r} / {plan.condition!r}\n"
            f"    reason={plan.verification_reason!r}"
        )


def ensure_system_user(db: Session) -> UUID:
    existing = db.execute(
        text("SELECT id FROM users WHERE username = :username"),
        {"username": SYSTEM_RESOLVER_USERNAME},
    ).scalar()
    if existing is not None:
        return existing

    role_id = db.execute(text("SELECT id FROM roles ORDER BY id LIMIT 1")).scalar()
    if role_id is None:
        raise RuntimeError("No roles row available to create system user.")

    user_id = db.execute(
        text(
            """
            INSERT INTO users (username, password_hash, full_name, role_id, is_active)
            VALUES (:username, :password_hash, :full_name, :role_id, false)
            RETURNING id
            """
        ),
        {
            "username": SYSTEM_RESOLVER_USERNAME,
            "password_hash": "!verification-duplicate-only-backfill-not-a-login",
            "full_name": SYSTEM_RESOLVER_FULL_NAME,
            "role_id": role_id,
        },
    ).scalar_one()
    db.flush()
    return user_id


def apply_plans(db: Session, plans: list[BackfillPlan]) -> int:
    if not plans:
        return 0

    resolver_id = ensure_system_user(db)
    updated = 0
    for plan in plans:
        result = db.execute(
            text(
                """
                UPDATE incidents
                SET verification_status = 'auto_processed',
                    verification_reason = NULL,
                    updated_at = NOW()
                WHERE id = :incident_id
                  AND is_deleted = false
                  AND verification_status = 'needs_verification'
                  AND duplicate_flag = false
                """
            ),
            {"incident_id": plan.incident_id},
        )
        if not result.rowcount:
            continue
        db.add(
            IncidentUpdate(
                incident_id=plan.incident_id,
                action=UpdateAction.status_change,
                old_values={
                    "verification_status": "needs_verification",
                    "verification_reason": plan.verification_reason,
                },
                new_values={
                    "verification_status": "auto_processed",
                    "verification_reason": None,
                },
                performed_by=resolver_id,
            )
        )
        updated += 1

    db.commit()
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or apply the duplicate-only verification status backfill."
        )
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--examples", type=int, default=5)
    args = parser.parse_args()

    db = _session()
    try:
        plans = fetch_plans(db)
        print_dry_run(plans, example_count=max(1, args.examples))
        if not args.apply:
            print(
                "\nDry run only — no database writes. "
                "Re-run with --apply after Najdi review."
            )
            return

        updated = apply_plans(db, plans)
        print(f"\nApplied: {updated} incidents updated.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
