#!/usr/bin/env python
"""Historical cleanup: re-evaluate pre–Phase-1 pending soft duplicate matches.

Phase 1 (``cbaf147``, 2026-09-07 12:51:07 +03) closed the Mansouri-class
false-positive window. Measurement showed most pending soft pairs still
predate that landing (median stored similarity 0.000). This script re-runs
the current ``DuplicateComparisonService.compare()`` against each historical
pair and proposes:

* ``distinct`` → mark ``duplicate_matches.status = 'false_positive'`` with a
  system resolver user (audit trail preserved; row is not deleted). Also clear
  ``incidents.duplicate_flag`` on either side when that side has no remaining
  pending soft matches (mirrors human ``resolve_duplicate`` false_positive for
  the reviewed incident).
* ``possible_duplicate`` / ``high_confidence_duplicate`` → leave ``pending``
  for human review.
* Unevaluable (gap ≤ 6h but neither text nor embedding similarity available,
  or event timestamps missing so gap cannot be computed) → leave ``pending``;
  do **not** silently treat as distinct.

Pairs that fail the current same-village + same-condition precondition are
treated as ``distinct`` (current callers would never consult the comparison
service for them).

STANDING CONVENTION: do not run ``--apply`` against production without Najdi
review. Default mode is dry-run / read-only.

Usage:
  python scripts/review/cleanup_historical_pending_duplicate_matches.py
  python scripts/review/cleanup_historical_pending_duplicate_matches.py --examples 8
  python scripts/review/cleanup_historical_pending_duplicate_matches.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import bindparam, create_engine, func, literal, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.text_normalization import normalize_arabic_sql
from app.news.services.dedup.duplicate_comparison_service import (
    DuplicateComparisonService,
    Verdict,
)

DEFAULT_DATABASE_URL = "postgresql+psycopg2://postgres:secret@localhost:5432/war_news_dev"
PHASE1_LANDED_AT = datetime.fromisoformat("2026-09-07T12:51:07+03:00")
SYSTEM_RESOLVER_USERNAME = "system.historical_dedup_reeval"
SYSTEM_RESOLVER_FULL_NAME = "System · Historical Dedup Re-evaluation"

ProposedStatus = Literal["false_positive", "leave_pending"]


def _session() -> Session:
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    if "@db:" in url:
        url = url.replace("@db:", "@localhost:")
    return sessionmaker(bind=create_engine(url))()


@dataclass(frozen=True)
class PairEvaluation:
    match_id: int
    incident_id: UUID
    matched_incident_id: UUID
    village: str | None
    condition: str | None
    same_village_id: bool
    same_condition_id: bool
    gap_seconds: float | None
    stored_similarity: float | None
    text_similarity: float | None
    embedding_similarity: float | None
    text_available: bool
    embedding_available: bool
    verdict: Verdict | None
    similarity_method: str | None
    proposed_status: ProposedStatus
    reason: str
    match_created_at: datetime


def _event_dt(event_date: Any, event_time: Any) -> datetime | None:
    if event_date is None:
        return None
    return datetime.combine(event_date, event_time or time(0, 0))


def _word_similarity(db: Session, a: str, b: str) -> float:
    """Match ``find_fast_dedup_candidates``: pg_trgm word_similarity on normalized text."""
    score = db.execute(
        select(
            func.word_similarity(
                normalize_arabic_sql(literal(a)),
                normalize_arabic_sql(literal(b)),
            )
        )
    ).scalar()
    return float(score or 0.0)


def fetch_and_evaluate(db: Session) -> list[PairEvaluation]:
    comparison = DuplicateComparisonService()
    gap_far = comparison.config.gap_far_seconds

    rows = db.execute(
        text(
            """
            SELECT
              dm.id AS match_id,
              dm.incident_id,
              dm.matched_incident_id,
              dm.similarity_score AS stored_similarity,
              dm.created_at AS match_created_at,
              i1.village_id AS village_id_1,
              i2.village_id AS village_id_2,
              i1.condition_id AS condition_id_1,
              i2.condition_id AS condition_id_2,
              i1.event_date AS event_date_1,
              i2.event_date AS event_date_2,
              i1.event_time AS event_time_1,
              i2.event_time AS event_time_2,
              i1.khabar AS khabar_1,
              i2.khabar AS khabar_2,
              CASE
                WHEN i1.khabar_embedding IS NOT NULL
                 AND i2.khabar_embedding IS NOT NULL
                THEN (1.0 - (i1.khabar_embedding <=> i2.khabar_embedding))
                ELSE NULL
              END AS embedding_similarity,
              COALESCE(v1.ref_name_en, v1.cad_name) AS village,
              c1.action_en AS condition
            FROM duplicate_matches dm
            JOIN incidents i1 ON i1.id = dm.incident_id
            JOIN incidents i2 ON i2.id = dm.matched_incident_id
            LEFT JOIN villages v1 ON v1.id = i1.village_id
            LEFT JOIN conditions c1 ON c1.id = i1.condition_id
            WHERE dm.status = 'pending'
              AND dm.match_type = 'soft'
              AND dm.matched_incident_id IS NOT NULL
              AND dm.created_at < CAST(:phase1_landed_at AS timestamptz)
            ORDER BY dm.id
            """
        ),
        {"phase1_landed_at": PHASE1_LANDED_AT.isoformat()},
    ).mappings().all()

    evaluations: list[PairEvaluation] = []
    for row in rows:
        same_village = row["village_id_1"] is not None and row["village_id_1"] == row["village_id_2"]
        same_condition = (
            row["condition_id_1"] is not None and row["condition_id_1"] == row["condition_id_2"]
        )
        dt1 = _event_dt(row["event_date_1"], row["event_time_1"])
        dt2 = _event_dt(row["event_date_2"], row["event_time_2"])
        gap: float | None
        if dt1 is None or dt2 is None:
            gap = None
        else:
            gap = abs((dt1 - dt2).total_seconds())

        k1 = (row["khabar_1"] or "").strip()
        k2 = (row["khabar_2"] or "").strip()
        text_available = bool(k1 and k2)
        text_sim: float | None = _word_similarity(db, k1, k2) if text_available else None
        emb_sim = (
            float(row["embedding_similarity"])
            if row["embedding_similarity"] is not None
            else None
        )
        embedding_available = emb_sim is not None

        verdict: Verdict | None = None
        method: str | None = None
        proposed: ProposedStatus
        reason: str

        if not same_village or not same_condition:
            verdict = "distinct"
            proposed = "false_positive"
            reason = "precondition_fail_village_or_condition"
        elif gap is None:
            proposed = "leave_pending"
            reason = "unevaluable_missing_event_timestamps"
        elif gap > gap_far:
            # Current compare() short-circuits to distinct beyond 6h without
            # requiring similarity inputs.
            result = comparison.compare(
                time_gap_seconds=gap,
                text_similarity=text_sim,
                embedding_similarity=emb_sim,
            )
            verdict = result.verdict
            method = result.similarity_method
            proposed = "false_positive"
            reason = "gap_over_6h_distinct"
        elif not text_available and not embedding_available:
            proposed = "leave_pending"
            reason = "unevaluable_no_text_or_embedding"
        else:
            result = comparison.compare(
                time_gap_seconds=gap,
                text_similarity=text_sim,
                embedding_similarity=emb_sim,
            )
            verdict = result.verdict
            method = result.similarity_method
            if verdict == "distinct":
                proposed = "false_positive"
                reason = f"compare_distinct_via_{method}"
            else:
                proposed = "leave_pending"
                reason = f"compare_{verdict}_via_{method}"

        evaluations.append(
            PairEvaluation(
                match_id=int(row["match_id"]),
                incident_id=row["incident_id"],
                matched_incident_id=row["matched_incident_id"],
                village=row["village"],
                condition=row["condition"],
                same_village_id=same_village,
                same_condition_id=same_condition,
                gap_seconds=gap,
                stored_similarity=(
                    float(row["stored_similarity"])
                    if row["stored_similarity"] is not None
                    else None
                ),
                text_similarity=text_sim,
                embedding_similarity=emb_sim,
                text_available=text_available,
                embedding_available=embedding_available,
                verdict=verdict,
                similarity_method=method,
                proposed_status=proposed,
                reason=reason,
                match_created_at=row["match_created_at"],
            )
        )
    return evaluations


def summarize(evaluations: list[PairEvaluation]) -> dict[str, int]:
    counts: dict[str, int] = {
        "total_historical_pending_soft": len(evaluations),
        "propose_false_positive": 0,
        "leave_pending_ambiguous": 0,
        "leave_pending_unevaluable": 0,
        "verdict_distinct": 0,
        "verdict_possible": 0,
        "verdict_high": 0,
        "verdict_none_unevaluable": 0,
        "precondition_fail": 0,
        "gap_over_6h": 0,
        "unevaluable_no_similarity": 0,
        "unevaluable_missing_timestamps": 0,
        "text_available": 0,
        "embedding_available": 0,
        "neither_similarity": 0,
    }
    for ev in evaluations:
        if ev.proposed_status == "false_positive":
            counts["propose_false_positive"] += 1
        elif ev.reason.startswith("unevaluable_"):
            counts["leave_pending_unevaluable"] += 1
        else:
            counts["leave_pending_ambiguous"] += 1

        if ev.verdict == "distinct":
            counts["verdict_distinct"] += 1
        elif ev.verdict == "possible_duplicate":
            counts["verdict_possible"] += 1
        elif ev.verdict == "high_confidence_duplicate":
            counts["verdict_high"] += 1
        else:
            counts["verdict_none_unevaluable"] += 1

        if ev.reason == "precondition_fail_village_or_condition":
            counts["precondition_fail"] += 1
        if ev.reason == "gap_over_6h_distinct":
            counts["gap_over_6h"] += 1
        if ev.reason == "unevaluable_no_text_or_embedding":
            counts["unevaluable_no_similarity"] += 1
        if ev.reason == "unevaluable_missing_event_timestamps":
            counts["unevaluable_missing_timestamps"] += 1
        if ev.text_available:
            counts["text_available"] += 1
        if ev.embedding_available:
            counts["embedding_available"] += 1
        if not ev.text_available and not ev.embedding_available:
            counts["neither_similarity"] += 1
    return counts


def print_summary(counts: dict[str, int]) -> None:
    print("=== Historical pending soft re-evaluation (dry-run classification) ===")
    print(f"Phase 1 landing cutoff: {PHASE1_LANDED_AT.isoformat()}")
    for key, value in counts.items():
        print(f"  {key}: {value}")


def _fmt_gap(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    if seconds < 120:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds/60:.1f}min"
    return f"{seconds/3600:.2f}h"


def print_examples(evaluations: list[PairEvaluation], limit: int) -> None:
    false_pos = [e for e in evaluations if e.proposed_status == "false_positive"]
    leave = [e for e in evaluations if e.proposed_status == "leave_pending"]

    def pick(pool: list[PairEvaluation], n: int) -> list[PairEvaluation]:
        if not pool:
            return []
        # Prefer variety: over-6h, precondition, near-threshold leave, unevaluable
        ordered = sorted(
            pool,
            key=lambda e: (
                0 if "gap_over_6h" in e.reason else 1,
                0 if "precondition" in e.reason else 1,
                0 if "unevaluable" in e.reason else 1,
                -(e.stored_similarity or 0.0),
            ),
        )
        return ordered[:n]

    fp_n = max(1, limit // 2)
    samples = pick(false_pos, fp_n) + pick(leave, limit - fp_n)
    print(f"\n=== Examples ({len(samples)}) ===")
    for ev in samples:
        print(
            f"\nmatch_id={ev.match_id}  proposed={ev.proposed_status}  "
            f"reason={ev.reason}"
        )
        print(
            f"  village={ev.village!r} condition={ev.condition!r} "
            f"same_v={ev.same_village_id} same_c={ev.same_condition_id}"
        )
        print(
            f"  gap={_fmt_gap(ev.gap_seconds)}  stored_sim={ev.stored_similarity}  "
            f"text_sim={ev.text_similarity}  emb_sim={ev.embedding_similarity}  "
            f"verdict={ev.verdict} method={ev.similarity_method}"
        )
        print(
            f"  incidents={ev.incident_id} ↔ {ev.matched_incident_id}  "
            f"created={ev.match_created_at}"
        )
        print(f"  old_status=pending → new_status={ev.proposed_status}")


def ensure_system_resolver(db: Session) -> UUID:
    existing = db.execute(
        text("SELECT id FROM users WHERE username = :u"),
        {"u": SYSTEM_RESOLVER_USERNAME},
    ).scalar()
    if existing is not None:
        return existing

    role_id = db.execute(text("SELECT id FROM roles ORDER BY id LIMIT 1")).scalar()
    if role_id is None:
        raise RuntimeError("No roles row available to create system resolver user.")

    # Unusable hash — this account is attribution-only, not for interactive login.
    user_id = db.execute(
        text(
            """
            INSERT INTO users (username, password_hash, full_name, role_id, is_active)
            VALUES (
              :username,
              :password_hash,
              :full_name,
              :role_id,
              false
            )
            RETURNING id
            """
        ),
        {
            "username": SYSTEM_RESOLVER_USERNAME,
            "password_hash": "!historical-dedup-reeval-not-a-login",
            "full_name": SYSTEM_RESOLVER_FULL_NAME,
            "role_id": role_id,
        },
    ).scalar()
    db.flush()
    return user_id


def apply_resolutions(db: Session, evaluations: list[PairEvaluation]) -> dict[str, int]:
    resolver_id = ensure_system_resolver(db)
    to_resolve = [e for e in evaluations if e.proposed_status == "false_positive"]
    match_ids = [e.match_id for e in to_resolve]

    updated_matches = 0
    if match_ids:
        result = db.execute(
            text(
                """
                UPDATE duplicate_matches
                SET status = 'false_positive',
                    resolved_by = :resolver_id
                WHERE id IN :ids
                  AND status = 'pending'
                  AND match_type = 'soft'
                """
            ).bindparams(bindparam("ids", expanding=True)),
            {"resolver_id": resolver_id, "ids": match_ids},
        )
        updated_matches = result.rowcount or 0

    # Clear duplicate_flag when an incident no longer has any pending soft pair.
    incident_ids = {
        eid
        for ev in to_resolve
        for eid in (ev.incident_id, ev.matched_incident_id)
    }
    cleared_flags = 0
    for incident_id in incident_ids:
        still_pending = db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM duplicate_matches
                WHERE status = 'pending'
                  AND match_type = 'soft'
                  AND matched_incident_id IS NOT NULL
                  AND (incident_id = :iid OR matched_incident_id = :iid)
                """
            ),
            {"iid": incident_id},
        ).scalar()
        if int(still_pending or 0) > 0:
            continue
        result = db.execute(
            text(
                """
                UPDATE incidents
                SET duplicate_flag = false,
                    updated_at = NOW()
                WHERE id = :iid
                  AND is_deleted = false
                  AND duplicate_flag = true
                """
            ),
            {"iid": incident_id},
        )
        cleared_flags += result.rowcount or 0

    db.commit()
    return {
        "matches_marked_false_positive": updated_matches,
        "duplicate_flags_cleared": cleared_flags,
        "resolver_user_id": str(resolver_id),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or apply historical re-evaluation of pre–Phase-1 pending "
            "soft duplicate_matches via DuplicateComparisonService."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist false_positive resolutions. Omit for dry-run (default).",
    )
    parser.add_argument(
        "--examples",
        type=int,
        default=8,
        help="How many before/after examples to print (default 8).",
    )
    args = parser.parse_args()

    db = _session()
    try:
        evaluations = fetch_and_evaluate(db)
        counts = summarize(evaluations)
        print_summary(counts)
        print_examples(evaluations, limit=max(1, args.examples))

        if not args.apply:
            print(
                "\nDry run only — no database writes. "
                "Re-run with --apply after Najdi review to persist."
            )
            return

        stats = apply_resolutions(db, evaluations)
        print("\nApplied:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
