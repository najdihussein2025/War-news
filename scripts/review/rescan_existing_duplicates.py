#!/usr/bin/env python
"""Re-scan active incidents for embedding-based duplicate signals.

Dry-run by default. ``--apply`` flags the later incident for human review;
even high-confidence results are never merged by this script.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.news.models import Condition, Incident, IncidentUpdate, UpdateAction, Village
from app.news.repositories.incident_repository import IncidentRepository
from app.news.services.dedup.duplicate_comparison_service import (
    DuplicateComparisonService,
)
from app.news.services.materialization.verification_signals import (
    _verification_reason,
)

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg2://postgres:secret@localhost:5432/war_news_dev"
)
SYSTEM_RESOLVER_USERNAME = "system.duplicate_rescan"
SYSTEM_RESOLVER_FULL_NAME = "System · Existing Duplicate Rescan"
SETTLED_STATUSES = frozenset({"verified", "rejected"})
DUPLICATE_VERDICTS = frozenset(
    {"possible_duplicate", "high_confidence_duplicate"}
)


def _session() -> Session:
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    if "@db:" in url:
        url = url.replace("@db:", "@localhost:")
    return sessionmaker(bind=create_engine(url))()


@dataclass(frozen=True)
class ScanIncident:
    id: UUID
    village_id: int | None
    condition_id: int | None
    village: str | None
    condition: str | None
    event_date: date
    event_time: time | None
    khabar: str
    khabar_embedding: list[float] | None
    duplicate_flag: bool
    verification_status: str

    @property
    def event_datetime(self) -> datetime:
        return datetime.combine(self.event_date, self.event_time or time.min)


@dataclass(frozen=True)
class DuplicatePlan:
    later: ScanIncident
    earlier: ScanIncident
    verdict: str
    time_gap_seconds: float
    embedding_similarity: float

    @property
    def duplicate_level(self) -> str:
        return "high" if self.verdict == "high_confidence_duplicate" else "medium"


@dataclass(frozen=True)
class ScanResult:
    pairs_evaluated: int
    verdict_counts: dict[str, int]
    skipped_missing_embedding: int
    plans: list[DuplicatePlan]


def fetch_active_incidents(db: Session) -> list[ScanIncident]:
    rows = db.execute(
        select(
            Incident,
            Village.ref_name_en,
            Village.cad_name,
            Condition.action_en,
        )
        .outerjoin(Village, Village.id == Incident.village_id)
        .outerjoin(Condition, Condition.id == Incident.condition_id)
        .where(Incident.is_deleted.is_(False))
        .order_by(
            Incident.village_id,
            Incident.condition_id,
            Incident.event_date,
            Incident.event_time,
            Incident.id,
        )
    ).all()
    return [
        ScanIncident(
            id=incident.id,
            village_id=incident.village_id,
            condition_id=incident.condition_id,
            village=ref_name_en or cad_name,
            condition=condition,
            event_date=incident.event_date,
            event_time=incident.event_time,
            khabar=incident.khabar,
            khabar_embedding=(
                list(incident.khabar_embedding)
                if incident.khabar_embedding is not None
                else None
            ),
            duplicate_flag=bool(incident.duplicate_flag),
            verification_status=incident.verification_status,
        )
        for incident, ref_name_en, cad_name, condition in rows
    ]


def cosine_similarity(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or not left:
        return None
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return None
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def scan_incidents(
    incidents: Iterable[ScanIncident],
    *,
    comparison: DuplicateComparisonService,
    lookup_window_days: int,
) -> ScanResult:
    groups: dict[tuple[int | None, int | None], list[ScanIncident]] = defaultdict(
        list
    )
    for incident in incidents:
        if incident.village_id is None or incident.condition_id is None:
            continue
        groups[(incident.village_id, incident.condition_id)].append(incident)

    candidate_pairs: list[tuple[ScanIncident, ScanIncident, float]] = []
    skipped_missing_embedding = 0
    window = timedelta(days=lookup_window_days)

    for group in groups.values():
        ordered = sorted(
            group, key=lambda item: (item.event_datetime, str(item.id))
        )
        for later_index, later in enumerate(ordered):
            if later.duplicate_flag or later.verification_status in SETTLED_STATUSES:
                continue
            for earlier in ordered[:later_index]:
                if (
                    earlier.duplicate_flag
                    or earlier.verification_status == "rejected"
                ):
                    continue
                gap = later.event_datetime - earlier.event_datetime
                if gap > window:
                    continue
                if (
                    earlier.khabar_embedding is None
                    or later.khabar_embedding is None
                ):
                    skipped_missing_embedding += 1
                    continue
                similarity = cosine_similarity(
                    earlier.khabar_embedding, later.khabar_embedding
                )
                if similarity is None:
                    skipped_missing_embedding += 1
                    continue
                candidate_pairs.append((later, earlier, similarity))

    candidate_pairs.sort(
        key=lambda pair: (
            pair[0].event_datetime,
            pair[0].event_datetime - pair[1].event_datetime,
            str(pair[1].id),
        )
    )

    counts = {
        "high_confidence_duplicate": 0,
        "possible_duplicate": 0,
        "distinct": 0,
    }
    plans: list[DuplicatePlan] = []
    newly_flagged_ids: set[UUID] = set()
    pairs_evaluated = 0

    for later, earlier, similarity in candidate_pairs:
        if later.id in newly_flagged_ids or earlier.id in newly_flagged_ids:
            continue
        gap_seconds = (
            later.event_datetime - earlier.event_datetime
        ).total_seconds()
        verdict = comparison.compare(
            time_gap_seconds=gap_seconds,
            text_similarity=None,
            embedding_similarity=similarity,
        ).verdict
        counts[verdict] += 1
        pairs_evaluated += 1
        if verdict in DUPLICATE_VERDICTS:
            plans.append(
                DuplicatePlan(
                    later=later,
                    earlier=earlier,
                    verdict=verdict,
                    time_gap_seconds=gap_seconds,
                    embedding_similarity=similarity,
                )
            )
            newly_flagged_ids.add(later.id)

    return ScanResult(
        pairs_evaluated=pairs_evaluated,
        verdict_counts=counts,
        skipped_missing_embedding=skipped_missing_embedding,
        plans=plans,
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
            "password_hash": "!duplicate-rescan-not-a-login",
            "full_name": SYSTEM_RESOLVER_FULL_NAME,
            "role_id": role_id,
        },
    ).scalar()
    db.flush()
    return user_id


def apply_plans(db: Session, plans: Iterable[DuplicatePlan]) -> int:
    plans = list(plans)
    if not plans:
        return 0
    resolver_id = ensure_system_user(db)
    repository = IncidentRepository(db)
    updated = 0

    for plan in plans:
        incidents = {
            incident.id: incident
            for incident in db.scalars(
                select(Incident)
                .where(Incident.id.in_([plan.later.id, plan.earlier.id]))
                .with_for_update()
            ).all()
        }
        later = incidents.get(plan.later.id)
        earlier = incidents.get(plan.earlier.id)
        if later is None or earlier is None:
            continue
        if (
            later.is_deleted
            or earlier.is_deleted
            or later.duplicate_flag
            or earlier.duplicate_flag
            or later.verification_status in SETTLED_STATUSES
            or earlier.verification_status == "rejected"
        ):
            continue

        old_values = {
            "duplicate_flag": bool(later.duplicate_flag),
            "verification_status": later.verification_status,
            "verification_reason": later.verification_reason,
            "duplicate_level": later.duplicate_level,
            "duplicate_similarity_score": later.duplicate_similarity_score,
        }
        reason = _verification_reason(
            None,
            duplicate_flag=True,
            duplicate_level=plan.duplicate_level,
            duplicate_similarity_score=plan.embedding_similarity,
        )
        later.duplicate_flag = True
        later.duplicate_level = plan.duplicate_level
        later.duplicate_similarity_score = plan.embedding_similarity
        later.verification_status = "needs_verification"
        later.verification_reason = reason
        db.add(later)
        repository.create_duplicate_match(
            incident=later,
            matched_incident=earlier,
            similarity_score=plan.embedding_similarity,
        )
        db.add(
            IncidentUpdate(
                incident_id=later.id,
                action=UpdateAction.status_change,
                old_values=old_values,
                new_values={
                    "duplicate_flag": True,
                    "duplicate_level": plan.duplicate_level,
                    "duplicate_similarity_score": plan.embedding_similarity,
                    "verification_status": "needs_verification",
                    "verification_reason": reason,
                    "matched_incident_id": str(earlier.id),
                    "embedding_similarity": plan.embedding_similarity,
                    "rescan_verdict": plan.verdict,
                },
                performed_by=resolver_id,
            )
        )
        updated += 1

    db.commit()
    return updated


def print_report(result: ScanResult, *, example_limit: int = 10) -> None:
    print("=== Existing incident duplicate rescan ===")
    print(f"Total pairs evaluated: {result.pairs_evaluated}")
    for verdict in (
        "high_confidence_duplicate",
        "possible_duplicate",
        "distinct",
    ):
        print(f"{verdict}: {result.verdict_counts[verdict]}")
    print(
        "Pairs skipped because an embedding was unavailable: "
        f"{result.skipped_missing_embedding}"
    )
    print(f"Incidents that would be flagged: {len(result.plans)}")

    examples = result.plans[:example_limit]
    print(f"\n=== Duplicate examples (showing {len(examples)}) ===")
    for index, plan in enumerate(examples, start=1):
        print(
            f"{index}. {plan.verdict} | "
            f"level={plan.duplicate_level} | "
            f"{plan.later.village or plan.earlier.village!r} / "
            f"{plan.later.condition or plan.earlier.condition!r}"
        )
        print(
            f"   earlier={plan.earlier.id} "
            f"{plan.earlier.event_datetime.isoformat()} "
            f"khabar={plan.earlier.khabar!r}"
        )
        print(
            f"   later={plan.later.id} "
            f"{plan.later.event_datetime.isoformat()} "
            f"khabar={plan.later.khabar!r}"
        )
        print(
            f"   gap_seconds={plan.time_gap_seconds:.0f} "
            f"embedding_similarity={plan.embedding_similarity:.4f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Re-scan active same-village/same-condition incidents using "
            "embedding similarity. Dry-run unless --apply is supplied."
        )
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--examples", type=int, default=10)
    args = parser.parse_args()

    db = _session()
    try:
        comparison = DuplicateComparisonService()
        result = scan_incidents(
            fetch_active_incidents(db),
            comparison=comparison,
            lookup_window_days=comparison.config.lookup_window_days,
        )
        print_report(result, example_limit=max(0, min(args.examples, 10)))
        if not args.apply:
            print("\nDry run only — no database writes.")
            return
        updated = apply_plans(db, result.plans)
        print(f"\nApplied: incidents_flagged={updated} (no incidents merged)")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
