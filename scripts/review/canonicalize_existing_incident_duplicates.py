#!/usr/bin/env python
"""Canonicalize existing same-event incidents.

Dry-run by default. Use ``--apply`` to merge and retire duplicates that share
the same canonical village and action, are no more than 30 minutes apart, and
meet the source-neutral semantic similarity policy.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.news.models import Incident, IncidentDetail
from app.news.repositories.incident_repository import IncidentRepository
from app.news.services.dedup.duplicate_comparison_service import (
    DuplicateComparisonService,
)
from app.news.services.dedup.incident_merge_service import IncidentMergeService

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg2://postgres:secret@localhost:5432/war_news_dev"
)


@dataclass(frozen=True)
class CanonicalizationPlan:
    canonical_id: UUID
    duplicate_id: UUID
    similarity_score: float
    similarity_method: str
    time_gap_seconds: float


def _session() -> Session:
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    return sessionmaker(bind=create_engine(url))()


def _event_datetime(incident: Incident) -> datetime | None:
    if incident.event_time is None:
        return None
    return datetime.combine(incident.event_date, incident.event_time)


def build_plans(db: Session) -> tuple[list[CanonicalizationPlan], int]:
    repository = IncidentRepository(db)
    comparison = DuplicateComparisonService()
    incidents = list(
        db.scalars(
            select(Incident)
            .where(
                Incident.is_deleted.is_(False),
                Incident.verification_status != "rejected",
                Incident.village_id.is_not(None),
                Incident.condition_id.is_not(None),
                Incident.raw_message_id.is_not(None),
                Incident.event_time.is_not(None),
            )
            .order_by(
                Incident.event_date,
                Incident.event_time,
                Incident.created_at,
                Incident.id,
            )
        ).all()
    )

    plans: list[CanonicalizationPlan] = []
    planned_duplicates: set[UUID] = set()
    skipped_missing_signal = 0
    for duplicate in incidents:
        duplicate_dt = _event_datetime(duplicate)
        if duplicate_dt is None or duplicate.id in planned_duplicates:
            continue
        candidates = repository.find_fast_dedup_candidates(
            village_id=duplicate.village_id,
            condition_id=duplicate.condition_id,
            message_datetime=duplicate_dt,
            lookup_window_days=1,
            candidate_text=duplicate.khabar,
            candidate_embedding=(
                list(duplicate.khabar_embedding)
                if duplicate.khabar_embedding is not None
                else None
            ),
            exclude_raw_message_id=duplicate.raw_message_id,
        )
        matched = False
        for candidate in candidates:
            canonical = candidate.incident
            canonical_dt = _event_datetime(canonical)
            if (
                canonical_dt is None
                or canonical_dt > duplicate_dt
                or canonical.id in planned_duplicates
            ):
                continue
            result = comparison.compare(
                time_gap_seconds=candidate.time_gap_seconds,
                text_similarity=candidate.text_similarity,
                embedding_similarity=candidate.embedding_similarity,
            )
            if result.verdict != "high_confidence_duplicate":
                continue
            plans.append(
                CanonicalizationPlan(
                    canonical_id=canonical.id,
                    duplicate_id=duplicate.id,
                    similarity_score=result.similarity_score,
                    similarity_method=result.similarity_method,
                    time_gap_seconds=result.time_gap_seconds,
                )
            )
            planned_duplicates.add(duplicate.id)
            matched = True
            break
        if not matched and duplicate.khabar_embedding is None and not duplicate.khabar:
            skipped_missing_signal += 1
    return plans, skipped_missing_signal


def _candidate_data(incident: Incident, detail: IncidentDetail | None) -> dict:
    excluded = {"id", "incident_id", "created_at", "updated_at"}
    mapped_fields = (
        {
            column.name: getattr(detail, column.name)
            for column in IncidentDetail.__table__.columns
            if column.name not in excluded
        }
        if detail is not None
        else {}
    )
    return {
        "deaths": incident.deaths,
        "injuries": incident.injuries,
        "total_deaths": incident.total_deaths,
        "total_injuries": incident.total_injuries,
        "khabar": incident.khabar,
        "mapped_fields": mapped_fields,
        "casualty_transitions": [],
    }


def apply_plans(db: Session, plans: list[CanonicalizationPlan]) -> int:
    repository = IncidentRepository(db)
    merge_service = IncidentMergeService(repository)
    applied = 0
    for plan in plans:
        try:
            rows = list(
                db.scalars(
                    select(Incident)
                    .where(
                        Incident.id.in_(
                            [plan.canonical_id, plan.duplicate_id]
                        )
                    )
                    .with_for_update()
                ).all()
            )
            by_id = {row.id: row for row in rows}
            canonical = by_id.get(plan.canonical_id)
            duplicate = by_id.get(plan.duplicate_id)
            if (
                canonical is None
                or duplicate is None
                or canonical.is_deleted
                or duplicate.is_deleted
                or canonical.village_id != duplicate.village_id
                or canonical.condition_id != duplicate.condition_id
                or canonical.raw_message_id is None
            ):
                db.rollback()
                continue
            canonical_dt = _event_datetime(canonical)
            duplicate_dt = _event_datetime(duplicate)
            if (
                canonical_dt is None
                or duplicate_dt is None
                or abs((duplicate_dt - canonical_dt).total_seconds()) > 1800
            ):
                db.rollback()
                continue
            detail = db.scalar(
                select(IncidentDetail).where(
                    IncidentDetail.incident_id == duplicate.id
                )
            )
            merge_service.canonicalize_existing(
                canonical=canonical,
                duplicate=duplicate,
                new_candidate_data=_candidate_data(duplicate, detail),
                similarity_score=plan.similarity_score,
            )
            db.commit()
            applied += 1
        except Exception:
            db.rollback()
            raise
    return applied


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the reported canonicalizations; default is dry-run.",
    )
    parser.add_argument("--examples", type=int, default=20)
    args = parser.parse_args()

    with _session() as db:
        plans, skipped = build_plans(db)
        print("=== Canonical incident duplicate scan ===")
        print(f"Candidates to canonicalize: {len(plans)}")
        print(f"Rows without a usable semantic signal: {skipped}")
        for index, plan in enumerate(plans[: max(args.examples, 0)], start=1):
            print(
                f"{index}. canonical={plan.canonical_id} "
                f"duplicate={plan.duplicate_id} "
                f"gap={plan.time_gap_seconds:.0f}s "
                f"{plan.similarity_method}={plan.similarity_score:.3f}"
            )
        if not args.apply:
            print("Dry-run only. Re-run with --apply after reviewing the report.")
            return
        print(f"Canonicalized: {apply_plans(db, plans)}")


if __name__ == "__main__":
    main()
