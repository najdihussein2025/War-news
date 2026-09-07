#!/usr/bin/env python
"""Historical cleanup: reconcile ``incidents.verification_status`` to current signals.

The column is the intended source of truth (see
``Docs/recon/verification-status-fix.md``), but it was written once at
materialization and drifted from live ``raw_messages.match_result`` / flags.

This script re-runs the same rules as
``_initial_verification_status`` against each active incident's *current*
match_result + ``duplicate_flag`` + relevance signals, and proposes column
corrections.

Decision (locked for this pass):
  * ``duplicate_flag`` alone **does** justify ``needs_verification`` — same as
    materialization-time helper and the verified rule set.
  * Village confidence is scoped to **target** villages only (origin low
    confidence must not force NV).
  * Human outcomes ``verified`` / ``rejected`` are left untouched.

STANDING CONVENTION: dry-run by default. Do not ``--apply`` without Najdi
review. Part 3b (API repoint) must not land until this apply is verified.

Usage:
  python scripts/review/reconcile_incident_verification_status.py
  python scripts/review/reconcile_incident_verification_status.py --examples 3
  python scripts/review/reconcile_incident_verification_status.py --apply
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
SYSTEM_RESOLVER_USERNAME = "system.verification_status_reconcile"
SYSTEM_RESOLVER_FULL_NAME = "System · Verification Status Reconcile"

Status = Literal["auto_processed", "needs_verification", "verified", "rejected"]


def _session() -> Session:
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    if "@db:" in url:
        url = url.replace("@db:", "@localhost:")
    return sessionmaker(bind=create_engine(url))()


@dataclass(frozen=True)
class ReconcilePlan:
    incident_id: UUID
    village: str | None
    condition: str | None
    duplicate_flag: bool
    current_status: Status
    proposed_status: Status
    reason: str
    any_village_low: bool
    condition_status: str | None
    target_statuses: str
    origin_low_only: bool
    relevance_needs_review: bool


def _relevance_needs_review_from_row(row: dict[str, Any]) -> bool:
    if bool(row.get("low_confidence_relevance")):
        return True
    filter_result = row.get("filter_result") or {}
    if isinstance(filter_result, dict) and filter_result.get("needs_review"):
        return True
    return False


def _classify_reason(
    *,
    current: Status,
    proposed: Status,
    duplicate_flag: bool,
    match_result: dict[str, Any],
    relevance_needs_review: bool,
    origin_low_only: bool,
) -> str:
    if current == proposed:
        if origin_low_only and current == "auto_processed":
            return "unchanged_origin_low_only_correct_auto"
        return "unchanged"
    if current in {"verified", "rejected"}:
        return "skip_human_outcome"
    if proposed == "needs_verification" and current == "auto_processed":
        if duplicate_flag:
            cond = match_result.get("condition_match_status")
            villages = match_result.get("village_matches") or []
            targets_ok = all(
                (v or {}).get("village_match_status") == "matched"
                for v in villages
                if (v or {}).get("village_role", "target") == "target"
            )
            if targets_ok and cond == "matched" and not relevance_needs_review:
                return "underflagged_duplicate_flag_only"
        if relevance_needs_review:
            return "underflagged_relevance"
        if match_result.get("condition_match_status") != "matched":
            return "underflagged_condition"
        return "underflagged_target_village"
    if proposed == "auto_processed" and current == "needs_verification":
        return "overflagged_stale_no_signal"
    return f"flip_{current}_to_{proposed}"


def _target_and_origin_summary(match_result: dict[str, Any]) -> tuple[str, bool]:
    villages = match_result.get("village_matches") or []
    target_parts: list[str] = []
    any_target_not_matched = False
    any_origin_low = False
    for village in villages:
        role = (village or {}).get("village_role", "target")
        status = (village or {}).get("village_match_status")
        if role == "target":
            target_parts.append(str(status))
            if status != "matched":
                any_target_not_matched = True
        elif status == "matched_low_confidence":
            any_origin_low = True
    origin_low_only = (
        any_origin_low
        and not any_target_not_matched
        and match_result.get("condition_match_status") == "matched"
    )
    return ",".join(target_parts) or "(none)", origin_low_only


def fetch_plans(db: Session) -> list[ReconcilePlan]:
    rows = db.execute(
        text(
            """
            SELECT
              i.id AS incident_id,
              i.verification_status,
              i.duplicate_flag,
              COALESCE(v.ref_name_en, v.cad_name) AS village,
              c.action_en AS condition,
              r.match_result,
              r.low_confidence_relevance,
              r.filter_result
            FROM incidents i
            LEFT JOIN raw_messages r ON r.id = i.raw_message_id
            LEFT JOIN villages v ON v.id = i.village_id
            LEFT JOIN conditions c ON c.id = i.condition_id
            WHERE i.is_deleted = false
              AND (r.id IS NULL OR NOT (r.raw_payload ? 'ocr_text'))
            ORDER BY i.created_at DESC
            """
        )
    ).mappings().all()

    plans: list[ReconcilePlan] = []
    for row in rows:
        current = row["verification_status"] or "auto_processed"
        if current in {"verified", "rejected"}:
            # Still emit as unchanged skip so counts are visible when asked.
            match_result = row["match_result"] if isinstance(row["match_result"], dict) else {}
            targets, origin_low_only = _target_and_origin_summary(match_result)
            plans.append(
                ReconcilePlan(
                    incident_id=row["incident_id"],
                    village=row["village"],
                    condition=row["condition"],
                    duplicate_flag=bool(row["duplicate_flag"]),
                    current_status=current,
                    proposed_status=current,
                    reason="skip_human_outcome",
                    any_village_low=bool(match_result.get("any_village_low_confidence")),
                    condition_status=match_result.get("condition_match_status"),
                    target_statuses=targets,
                    origin_low_only=origin_low_only,
                    relevance_needs_review=_relevance_needs_review_from_row(dict(row)),
                )
            )
            continue

        match_result = row["match_result"] if isinstance(row["match_result"], dict) else {}
        relevance = _relevance_needs_review_from_row(dict(row))
        proposed = _initial_verification_status(
            match_result,
            duplicate_flag=bool(row["duplicate_flag"]),
            relevance_needs_review=relevance,
        )
        targets, origin_low_only = _target_and_origin_summary(match_result)
        reason = _classify_reason(
            current=current,
            proposed=proposed,  # type: ignore[arg-type]
            duplicate_flag=bool(row["duplicate_flag"]),
            match_result=match_result,
            relevance_needs_review=relevance,
            origin_low_only=origin_low_only,
        )
        plans.append(
            ReconcilePlan(
                incident_id=row["incident_id"],
                village=row["village"],
                condition=row["condition"],
                duplicate_flag=bool(row["duplicate_flag"]),
                current_status=current,
                proposed_status=proposed,  # type: ignore[arg-type]
                reason=reason,
                any_village_low=bool(match_result.get("any_village_low_confidence")),
                condition_status=match_result.get("condition_match_status"),
                target_statuses=targets,
                origin_low_only=origin_low_only,
                relevance_needs_review=relevance,
            )
        )
    return plans


def summarize(plans: list[ReconcilePlan]) -> dict[str, int]:
    counts: dict[str, int] = {
        "active_in_scope": len(plans),
        "unchanged": 0,
        "flip_to_needs_verification": 0,
        "flip_to_auto_processed": 0,
        "skip_human_outcome": 0,
        "underflagged_target_village": 0,
        "underflagged_condition": 0,
        "underflagged_duplicate_flag_only": 0,
        "underflagged_relevance": 0,
        "overflagged_stale_no_signal": 0,
        "unchanged_origin_low_only_correct_auto": 0,
    }
    for plan in plans:
        if plan.reason == "unchanged":
            counts["unchanged"] += 1
        elif plan.reason == "skip_human_outcome":
            counts["skip_human_outcome"] += 1
        elif plan.reason == "unchanged_origin_low_only_correct_auto":
            counts["unchanged_origin_low_only_correct_auto"] += 1
            counts["unchanged"] += 1
        elif plan.proposed_status == "needs_verification" and plan.current_status == "auto_processed":
            counts["flip_to_needs_verification"] += 1
            if plan.reason in counts:
                counts[plan.reason] += 1
        elif plan.proposed_status == "auto_processed" and plan.current_status == "needs_verification":
            counts["flip_to_auto_processed"] += 1
            if plan.reason in counts:
                counts[plan.reason] += 1
    return counts


def print_summary(counts: dict[str, int]) -> None:
    print("=== verification_status reconcile (dry-run classification) ===")
    print(
        "Rules: _initial_verification_status; duplicate_flag alone => NV; "
        "target villages only; verified/rejected untouched."
    )
    for key, value in counts.items():
        print(f"  {key}: {value}")


def print_examples(plans: list[ReconcilePlan], per_bucket: int) -> None:
    buckets = [
        "underflagged_target_village",
        "underflagged_condition",
        "underflagged_duplicate_flag_only",
        "overflagged_stale_no_signal",
        "unchanged_origin_low_only_correct_auto",
    ]
    print(f"\n=== Examples (up to {per_bucket} per subcase) ===")
    for bucket in buckets:
        samples = [p for p in plans if p.reason == bucket][:per_bucket]
        if not samples and bucket == "unchanged_origin_low_only_correct_auto":
            # Fall back: origin_low_only with auto_processed unchanged
            samples = [
                p
                for p in plans
                if p.origin_low_only
                and p.current_status == "auto_processed"
                and p.proposed_status == "auto_processed"
            ][:per_bucket]
        print(f"\n-- {bucket} (n_shown={len(samples)}) --")
        for plan in samples:
            print(
                f"  {plan.incident_id}  {plan.village!r} / {plan.condition!r}\n"
                f"    {plan.current_status} → {plan.proposed_status}  "
                f"dup_flag={plan.duplicate_flag} cond={plan.condition_status} "
                f"targets=[{plan.target_statuses}] any_low={plan.any_village_low} "
                f"origin_low_only={plan.origin_low_only}"
            )


def ensure_system_user(db: Session) -> UUID:
    existing = db.execute(
        text("SELECT id FROM users WHERE username = :u"),
        {"u": SYSTEM_RESOLVER_USERNAME},
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
            "password_hash": "!verification-status-reconcile-not-a-login",
            "full_name": SYSTEM_RESOLVER_FULL_NAME,
            "role_id": role_id,
        },
    ).scalar()
    db.flush()
    return user_id


def apply_plans(db: Session, plans: list[ReconcilePlan]) -> dict[str, int]:
    resolver_id = ensure_system_user(db)
    flips = [
        p
        for p in plans
        if p.current_status != p.proposed_status
        and p.current_status not in {"verified", "rejected"}
    ]
    updated = 0
    for plan in flips:
        result = db.execute(
            text(
                """
                UPDATE incidents
                SET verification_status = :new_status,
                    verified_by_user_id = CASE
                      WHEN :new_status = 'needs_verification' THEN NULL
                      ELSE verified_by_user_id
                    END,
                    verified_at = CASE
                      WHEN :new_status = 'needs_verification' THEN NULL
                      ELSE verified_at
                    END,
                    updated_at = NOW()
                WHERE id = :iid
                  AND is_deleted = false
                  AND verification_status = :old_status
                """
            ),
            {
                "iid": plan.incident_id,
                "new_status": plan.proposed_status,
                "old_status": plan.current_status,
            },
        )
        updated += result.rowcount or 0
    db.commit()
    return {
        "rows_updated": updated,
        "resolver_user_id": str(resolver_id),
        "note": "resolver reserved for audit attribution; column update is direct",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or apply reconciliation of incidents.verification_status "
            "from current match/duplicate/relevance signals."
        )
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--examples", type=int, default=3)
    args = parser.parse_args()

    db = _session()
    try:
        plans = fetch_plans(db)
        counts = summarize(plans)
        print_summary(counts)
        print_examples(plans, per_bucket=max(1, args.examples))

        if not args.apply:
            print(
                "\nDry run only — no database writes. "
                "Re-run with --apply after Najdi review to persist. "
                "Do not repoint the API until this apply is verified."
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
