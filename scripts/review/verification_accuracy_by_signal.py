#!/usr/bin/env python
"""Measure verification-signal accuracy against human review outcomes.

Read-only first-pass report. This script never writes database rows and has no
``--apply`` flag, so it is safe to run repeatedly.

Known limitation: ``field_was_corrected`` checks whether any edit exists in the
incident's history for the tracked fields. It does not prove the edit happened
in the same review session as the verify/reject click; a reviewer could have
made an unrelated edit at another time.

Usage:
  python scripts/review/verification_accuracy_by_signal.py
  python scripts/review/verification_accuracy_by_signal.py --examples 5
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

from app.news.services.materialization.incident_materialization_service import (
    _initial_verification_status,
)
from app.news.services.materialization.verification_signals import (
    _verification_reason,
)

DEFAULT_DATABASE_URL = "postgresql+psycopg2://postgres:secret@localhost:5432/war_news_dev"

Bucket = Literal[
    "hard_signal",
    "confidence_only_single",
    "confidence_only_multi",
    "auto_processed_now",
]
Status = Literal["auto_processed", "needs_verification", "verified", "rejected"]

CORRECTION_FIELDS = {
    "village_id",
    "condition_id",
    "deaths",
    "injuries",
    "total_deaths",
    "total_injuries",
}
BUCKETS: tuple[Bucket, ...] = (
    "hard_signal",
    "confidence_only_single",
    "confidence_only_multi",
    "auto_processed_now",
)
CASUALTY_REASON_MARKERS = (
    "Casualty count may be incomplete",
    "possible_missed_casualty_transition",
    "casualty transition",
)


def _session() -> Session:
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    if "@db:" in url:
        url = url.replace("@db:", "@localhost:")
    return sessionmaker(bind=create_engine(url))()


@dataclass(frozen=True)
class SignalClassification:
    bucket: Bucket
    recomputed_status: Status
    signals: tuple[str, ...]
    reason: str | None


@dataclass(frozen=True)
class IncidentRow:
    incident_id: UUID
    village: str | None
    condition: str | None
    final_status: Literal["verified", "rejected"]
    duplicate_flag: bool
    duplicate_level: str | None
    duplicate_similarity_score: float | None
    verification_reason: str | None
    match_result: dict[str, Any]
    relevance_needs_review: bool


@dataclass(frozen=True)
class ClassifiedIncident:
    row: IncidentRow
    classification: SignalClassification
    field_was_corrected: bool = False


@dataclass
class BucketSummary:
    total: int = 0
    rejected: int = 0
    verified_with_correction: int = 0
    verified_no_correction: int = 0
    examples: list[ClassifiedIncident] = field(default_factory=list)

    @property
    def correction_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.rejected + self.verified_with_correction) / self.total


def _relevance_needs_review_from_row(row: dict[str, Any]) -> bool:
    if bool(row.get("low_confidence_relevance")):
        return True
    filter_result = row.get("filter_result") or {}
    if isinstance(filter_result, dict) and filter_result.get("needs_review"):
        return True
    return False


def _casualty_transition_signal(reason: str | None) -> bool:
    text_value = reason or ""
    return any(marker in text_value for marker in CASUALTY_REASON_MARKERS)


def classify_signal_bucket(
    match_result: dict[str, Any] | None,
    *,
    duplicate_flag: bool = False,
    duplicate_level: str | None = None,
    duplicate_similarity_score: float | None = None,
    relevance_needs_review: bool = False,
    verification_reason: str | None = None,
) -> SignalClassification:
    """Return the signal bucket using the current materialization rules."""
    result = match_result if isinstance(match_result, dict) else {}
    recomputed_status = _initial_verification_status(
        result,
        duplicate_flag=duplicate_flag,
    )
    recomputed_reason = _verification_reason(
        result,
        duplicate_flag=duplicate_flag,
        duplicate_level=duplicate_level,
        duplicate_similarity_score=duplicate_similarity_score,
    )
    reason = recomputed_reason or verification_reason

    signals: list[str] = []
    hard_signal = False
    if duplicate_flag:
        hard_signal = True
        signals.append("duplicate_flag")
    if relevance_needs_review:
        signals.append("relevance_needs_review")
    if _casualty_transition_signal(reason):
        signals.append("possible_missed_casualty_transition")

    condition_status = result.get("condition_match_status")
    if condition_status != "matched":
        signals.append(f"condition:{condition_status or 'missing'}")

    for index, village in enumerate(result.get("village_matches") or [], start=1):
        if (village or {}).get("village_role", "target") != "target":
            continue
        village_status = (village or {}).get("village_match_status")
        if village_status != "matched":
            label = (village or {}).get("raw_village_text") or f"target#{index}"
            signals.append(f"target_village:{label}:{village_status or 'missing'}")

    if hard_signal:
        return SignalClassification(
            "hard_signal",
            recomputed_status,  # type: ignore[arg-type]
            tuple(signals),
            reason,
        )
    if recomputed_status == "auto_processed":
        return SignalClassification(
            "auto_processed_now",
            "auto_processed",
            tuple(signals),
            reason,
        )

    confidence_count = len(signals)
    if confidence_count <= 1:
        return SignalClassification(
            "confidence_only_single",
            "needs_verification",
            tuple(signals),
            reason,
        )
    return SignalClassification(
        "confidence_only_multi",
        "needs_verification",
        tuple(signals),
        reason,
    )


def fetch_reviewed_incidents(db: Session) -> list[IncidentRow]:
    rows = db.execute(
        text(
            """
            SELECT
              i.id AS incident_id,
              i.verification_status,
              i.verification_reason,
              i.duplicate_flag,
              i.duplicate_level,
              i.duplicate_similarity_score,
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
              AND i.verification_status IN ('verified', 'rejected')
              AND (r.id IS NULL OR NOT (r.raw_payload ? 'ocr_text'))
            ORDER BY i.created_at DESC
            """
        )
    ).mappings().all()

    incidents: list[IncidentRow] = []
    for row in rows:
        row_dict = dict(row)
        match_result = row["match_result"] if isinstance(row["match_result"], dict) else {}
        incidents.append(
            IncidentRow(
                incident_id=row["incident_id"],
                village=row["village"],
                condition=row["condition"],
                final_status=row["verification_status"],
                duplicate_flag=bool(row["duplicate_flag"]),
                duplicate_level=row["duplicate_level"],
                duplicate_similarity_score=(
                    float(row["duplicate_similarity_score"])
                    if row["duplicate_similarity_score"] is not None
                    else None
                ),
                verification_reason=row["verification_reason"],
                match_result=match_result,
                relevance_needs_review=_relevance_needs_review_from_row(row_dict),
            )
        )
    return incidents


def _edit_changed_tracked_field(old_values: Any, new_values: Any) -> bool:
    if not isinstance(old_values, dict) or not isinstance(new_values, dict):
        return False
    for key in CORRECTION_FIELDS:
        if key in old_values and key in new_values and old_values[key] != new_values[key]:
            return True
    return False


def fetch_corrected_incident_ids(db: Session, incident_ids: list[UUID]) -> set[UUID]:
    if not incident_ids:
        return set()
    statement = (
        text(
            """
            SELECT incident_id, old_values, new_values
            FROM incident_updates
            WHERE action = 'edit'
              AND incident_id IN :incident_ids
            """
        )
        .bindparams(bindparam("incident_ids", expanding=True))
    )
    rows = db.execute(statement, {"incident_ids": incident_ids}).mappings().all()
    corrected: set[UUID] = set()
    for row in rows:
        if _edit_changed_tracked_field(row["old_values"], row["new_values"]):
            corrected.add(row["incident_id"])
    return corrected


def classify_incidents(
    rows: list[IncidentRow],
    corrected_ids: set[UUID],
) -> list[ClassifiedIncident]:
    classified: list[ClassifiedIncident] = []
    for row in rows:
        classified.append(
            ClassifiedIncident(
                row=row,
                classification=classify_signal_bucket(
                    row.match_result,
                    duplicate_flag=row.duplicate_flag,
                    duplicate_level=row.duplicate_level,
                    duplicate_similarity_score=row.duplicate_similarity_score,
                    relevance_needs_review=row.relevance_needs_review,
                    verification_reason=row.verification_reason,
                ),
                field_was_corrected=row.incident_id in corrected_ids,
            )
        )
    return classified


def summarize(classified: list[ClassifiedIncident]) -> dict[Bucket, BucketSummary]:
    summaries = {bucket: BucketSummary() for bucket in BUCKETS}
    for item in classified:
        summary = summaries[item.classification.bucket]
        summary.total += 1
        if item.row.final_status == "rejected":
            summary.rejected += 1
        elif item.field_was_corrected:
            summary.verified_with_correction += 1
        else:
            summary.verified_no_correction += 1
        summary.examples.append(item)
    return summaries


def print_summary(summaries: dict[Bucket, BucketSummary]) -> None:
    print("=== verification accuracy by signal (read-only; no writes) ===")
    print(
        "bucket | total | rejected | verified_with_correction | "
        "verified_no_correction | correction_rate"
    )
    for bucket in BUCKETS:
        summary = summaries[bucket]
        print(
            f"{bucket} | {summary.total} | {summary.rejected} | "
            f"{summary.verified_with_correction} | "
            f"{summary.verified_no_correction} | "
            f"{summary.correction_rate:.1%}"
        )


def print_examples(
    summaries: dict[Bucket, BucketSummary],
    *,
    per_bucket: int,
) -> None:
    print(f"\n=== Examples (up to {per_bucket} per bucket) ===")
    for bucket in BUCKETS:
        examples = summaries[bucket].examples[:per_bucket]
        print(f"\n-- {bucket} (n_shown={len(examples)}) --")
        for item in examples:
            signals = ", ".join(item.classification.signals) or "(none)"
            print(
                f"  {item.row.incident_id}  "
                f"{item.row.village!r} / {item.row.condition!r}\n"
                f"    signals=[{signals}] final={item.row.final_status} "
                f"corrected={item.field_was_corrected}"
            )


def print_signal_counts(classified: list[ClassifiedIncident]) -> None:
    counts: dict[Bucket, Counter[str]] = defaultdict(Counter)
    for item in classified:
        bucket = item.classification.bucket
        for signal in item.classification.signals or ("(none)",):
            counts[bucket][signal] += 1

    print("\n=== Signal counts by bucket ===")
    for bucket in BUCKETS:
        print(f"\n-- {bucket} --")
        for signal, count in counts[bucket].most_common(10):
            print(f"  {signal}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only report of reviewed incident outcomes by original "
            "verification signal. This script never writes to the database."
        )
    )
    parser.add_argument("--examples", type=int, default=5)
    args = parser.parse_args()

    db = _session()
    try:
        rows = fetch_reviewed_incidents(db)
        corrected_ids = fetch_corrected_incident_ids(
            db,
            [row.incident_id for row in rows],
        )
        classified = classify_incidents(rows, corrected_ids)
        summaries = summarize(classified)
        print_summary(summaries)
        print_examples(summaries, per_bucket=max(0, args.examples))
        print_signal_counts(classified)
        print("\nRead-only complete: no database writes were attempted.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
