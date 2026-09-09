#!/usr/bin/env python
"""Historical cleanup: clear orphaned ``incidents.duplicate_flag`` rows.

After Part 2's Tier-2 backstop fix, new orphans should not be created on that
path. This script addresses the *existing* backlog: active incidents with
``duplicate_flag = true`` and no actionable outgoing pending
``duplicate_matches`` row.

These flags are not reviewable in the UI (resolve requires a pending match),
so the approved treatment is to clear the flag. Patterns from the Part 2
recon:

* B / C2 — Tier-2 backstop set the flag without a match (~77)
* C — pre-clear-fix merge retained the flag (~43)
* D — legacy Sep 2 creates with no match machinery (~41)
* A — fast-path edge cases (small)

Pattern D is treated the same as B/C after a fingerprint check: if there is
still no pending match with this incident as the duplicate, there is nothing
to review against. A row where this incident is only the suggested canonical
target for another duplicate does not make this incident reviewable.

When clearing the flag, also re-evaluate ``verification_status`` with
``_initial_verification_status`` so a flag-only NV does not remain after the
flag is removed (unless village/condition/relevance still warrant NV).

STANDING CONVENTION: dry-run by default. Do not ``--apply`` without Najdi
review.

Usage:
  python scripts/review/cleanup_orphaned_duplicate_flags.py
  python scripts/review/cleanup_orphaned_duplicate_flags.py --examples 8
  python scripts/review/cleanup_orphaned_duplicate_flags.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.news.services.materialization.incident_materialization_service import (
    _initial_verification_status,
)

DEFAULT_DATABASE_URL = "postgresql+psycopg2://postgres:secret@localhost:5432/war_news_dev"
SYSTEM_USERNAME = "system.orphan_duplicate_flag_cleanup"
SYSTEM_FULL_NAME = "System · Orphan Duplicate Flag Cleanup"

Pattern = Literal["tier2_backstop", "pre_clear_merge", "legacy_or_other", "post_clear_then_tier2"]


def _session() -> Session:
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    if "@db:" in url:
        url = url.replace("@db:", "@localhost:")
    return sessionmaker(bind=create_engine(url))()


@dataclass(frozen=True)
class OrphanPlan:
    incident_id: UUID
    village: str | None
    condition: str | None
    verification_status: str
    proposed_verification_status: str
    pattern: Pattern
    tier2_completed_at: Any
    has_pipeline_merge: bool
    last_merge_at: Any
    created_at: Any
    reason: str


def _relevance(row: dict[str, Any]) -> bool:
    if bool(row.get("low_confidence_relevance")):
        return True
    fr = row.get("filter_result") or {}
    return bool(isinstance(fr, dict) and fr.get("needs_review"))


def _fingerprint(row: dict[str, Any]) -> Pattern:
    tier2 = row.get("tier2_completed_at")
    has_merge = bool(row.get("has_pipeline_merge"))
    last_merge = row.get("last_merge_at")
    if tier2 is not None and has_merge and last_merge is not None and tier2 > last_merge:
        return "post_clear_then_tier2"
    if tier2 is not None and not has_merge:
        return "tier2_backstop"
    if has_merge and last_merge is not None:
        # Compare as timestamptz string-ish via Python
        return "pre_clear_merge"
    return "legacy_or_other"


def fetch_plans(db: Session) -> list[OrphanPlan]:
    rows = db.execute(
        text(
            """
            SELECT
              i.id AS incident_id,
              i.verification_status,
              i.duplicate_flag,
              i.created_at,
              COALESCE(v.ref_name_en, v.cad_name) AS village,
              c.action_en AS condition,
              r.match_result,
              r.low_confidence_relevance,
              r.filter_result,
              r.tier2_completed_at,
              r.fast_path_completed_at,
              EXISTS (
                SELECT 1 FROM incident_updates iu
                WHERE iu.incident_id = i.id AND iu.action = 'pipeline_merge'
              ) AS has_pipeline_merge,
              (
                SELECT MAX(iu.created_at) FROM incident_updates iu
                WHERE iu.incident_id = i.id AND iu.action = 'pipeline_merge'
              ) AS last_merge_at
            FROM incidents i
            LEFT JOIN raw_messages r ON r.id = i.raw_message_id
            LEFT JOIN villages v ON v.id = i.village_id
            LEFT JOIN conditions c ON c.id = i.condition_id
            WHERE i.is_deleted = false
              AND i.duplicate_flag = true
              AND NOT EXISTS (
                SELECT 1 FROM duplicate_matches dm
                WHERE dm.incident_id = i.id
                  AND dm.status = 'pending'
                  AND dm.matched_incident_id IS NOT NULL
              )
            ORDER BY i.created_at DESC
            """
        )
    ).mappings().all()

    plans: list[OrphanPlan] = []
    for row in rows:
        match_result = row["match_result"] if isinstance(row["match_result"], dict) else {}
        # After clearing the flag, recompute verification without it.
        proposed_vs = _initial_verification_status(
            match_result,
            duplicate_flag=False,
        )
        pattern = _fingerprint(dict(row))
        plans.append(
            OrphanPlan(
                incident_id=row["incident_id"],
                village=row["village"],
                condition=row["condition"],
                verification_status=row["verification_status"] or "auto_processed",
                proposed_verification_status=proposed_vs,
                pattern=pattern,
                tier2_completed_at=row["tier2_completed_at"],
                has_pipeline_merge=bool(row["has_pipeline_merge"]),
                last_merge_at=row["last_merge_at"],
                created_at=row["created_at"],
                reason="clear_orphan_flag_no_match_row",
            )
        )
    return plans


def summarize(plans: list[OrphanPlan]) -> dict[str, int]:
    counts: dict[str, int] = {
        "orphans_total": len(plans),
        "pattern_tier2_backstop": 0,
        "pattern_post_clear_then_tier2": 0,
        "pattern_pre_clear_merge": 0,
        "pattern_legacy_or_other": 0,
        "also_flip_verification_to_auto": 0,
        "keep_needs_verification_after_clear": 0,
    }
    for plan in plans:
        counts[f"pattern_{plan.pattern}"] += 1
        if (
            plan.verification_status == "needs_verification"
            and plan.proposed_verification_status == "auto_processed"
        ):
            counts["also_flip_verification_to_auto"] += 1
        elif plan.proposed_verification_status == "needs_verification":
            counts["keep_needs_verification_after_clear"] += 1
    return counts


def print_summary(counts: dict[str, int]) -> None:
    print("=== Orphan duplicate_flag cleanup (dry-run) ===")
    print(
        "Scope: active incidents with duplicate_flag=true and no actionable "
        "outgoing pending duplicate match."
    )
    for key, value in counts.items():
        print(f"  {key}: {value}")


def print_examples(plans: list[OrphanPlan], limit: int) -> None:
    by_pattern: dict[str, list[OrphanPlan]] = {}
    for plan in plans:
        by_pattern.setdefault(plan.pattern, []).append(plan)
    print(f"\n=== Examples (up to {limit} per pattern) ===")
    for pattern, group in by_pattern.items():
        print(f"\n-- {pattern} --")
        for plan in group[:limit]:
            print(
                f"  {plan.incident_id}  {plan.village!r} / {plan.condition!r}\n"
                f"    flag true → false; verification "
                f"{plan.verification_status} → {plan.proposed_verification_status}; "
                f"tier2={plan.tier2_completed_at}; merge={plan.has_pipeline_merge}"
            )


def ensure_system_user(db: Session) -> UUID:
    existing = db.execute(
        text("SELECT id FROM users WHERE username = :u"),
        {"u": SYSTEM_USERNAME},
    ).scalar()
    if existing is not None:
        return existing
    role_id = db.execute(text("SELECT id FROM roles ORDER BY id LIMIT 1")).scalar()
    if role_id is None:
        raise RuntimeError("No roles row available to create system user.")
    return db.execute(
        text(
            """
            INSERT INTO users (username, password_hash, full_name, role_id, is_active)
            VALUES (:username, :password_hash, :full_name, :role_id, false)
            RETURNING id
            """
        ),
        {
            "username": SYSTEM_USERNAME,
            "password_hash": "!orphan-flag-cleanup-not-a-login",
            "full_name": SYSTEM_FULL_NAME,
            "role_id": role_id,
        },
    ).scalar()


def apply_plans(db: Session, plans: list[OrphanPlan]) -> dict[str, int]:
    resolver_id = ensure_system_user(db)
    cleared = 0
    vs_updated = 0
    for plan in plans:
        result = db.execute(
            text(
                """
                UPDATE incidents
                SET duplicate_flag = false,
                    verification_status = :vs,
                    updated_at = NOW()
                WHERE id = :iid
                  AND is_deleted = false
                  AND duplicate_flag = true
                  AND NOT EXISTS (
                    SELECT 1 FROM duplicate_matches dm
                    WHERE dm.incident_id = incidents.id
                      AND dm.status = 'pending'
                      AND dm.matched_incident_id IS NOT NULL
                  )
                """
            ),
            {"iid": plan.incident_id, "vs": plan.proposed_verification_status},
        )
        if result.rowcount:
            cleared += 1
            if plan.verification_status != plan.proposed_verification_status:
                vs_updated += 1
    db.commit()
    return {
        "flags_cleared": cleared,
        "verification_status_updated": vs_updated,
        "resolver_user_id": str(resolver_id),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or apply cleanup of orphaned duplicate_flag rows with no "
            "actionable outgoing pending duplicate match."
        )
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--examples", type=int, default=5)
    args = parser.parse_args()

    db = _session()
    try:
        plans = fetch_plans(db)
        counts = summarize(plans)
        print_summary(counts)
        print_examples(plans, limit=max(1, args.examples))
        if not args.apply:
            print(
                "\nDry run only — no database writes. "
                "Re-run with --apply after Najdi review to persist."
            )
            return
        stats = apply_plans(db, plans)
        print("\nApplied:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
