#!/usr/bin/env python
"""Retroactive cleanup: merge cross-village near-duplicate incident clusters.

Uses Part 1c's cross-village backstop as the evaluation standard:

* same ``condition_id``
* different ``village_id``
* different ``raw_message_id``
* each raw_message produced exactly one active incident (excludes
  multi-village daily-summary fan-out; those stay as separate rows)
* |Δ message_datetime| ≤ 30 minutes (``dedup_fastpath_gap_mid_seconds``)
* ``word_similarity(khabar)`` ≥ ``dedup_cross_village_text_min`` (0.87)

Clusters are formed by union-find over qualifying pairs. Canonical incident =
earliest ``message_datetime`` (fallback ``received_at`` / ``created_at``).

On ``--apply`` each non-canonical row is merged into the canonical via
``IncidentMergeService`` (same path as live fast-path), then soft-deleted
(``is_deleted = true``) with a ``confirmed_duplicate`` ``duplicate_matches``
row — matching human ``resolve_duplicate`` confirmed behaviour. No hard deletes.

STANDING CONVENTION: dry-run by default. Do not ``--apply`` without Najdi review.

Usage:
  python scripts/review/cleanup_cross_village_duplicate_clusters.py
  python scripts/review/cleanup_cross_village_duplicate_clusters.py --examples 8
  python scripts/review/cleanup_cross_village_duplicate_clusters.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import create_engine, func, literal, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.text_normalization import normalize_arabic_sql
from app.news.models import DuplicateMatch, Incident, MatchStatus, MatchType, Village
from app.news.models.raw_message import RawMessage
from app.news.repositories.incident_repository import IncidentRepository
from app.news.services.dedup.duplicate_comparison_service import (
    DuplicateComparisonConfig,
)
from app.news.services.dedup.incident_merge_service import IncidentMergeService

DEFAULT_DATABASE_URL = "postgresql+psycopg2://postgres:secret@localhost:5432/war_news_dev"
LOOKBACK_DAYS = 14
# Highlight the motivating Sep 7 maslakh cluster raw_message ids.
NABATIYEH_CLUSTER_RAW_IDS = frozenset(
    {8541, 8543, 8547, 8550, 8553, 8554, 8557, 8558, 8561, 8563, 8564, 8565}
)


def _session() -> Session:
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    # Host-side runs need localhost; in-compose containers keep hostname `db`.
    if "@db:" in url and not Path("/.dockerenv").exists():
        url = url.replace("@db:", "@localhost:")
    return sessionmaker(bind=create_engine(url))()


@dataclass
class IncidentRow:
    id: UUID
    raw_message_id: int | None
    village_id: int
    village_name: str
    condition_id: int
    khabar: str
    event_date: Any
    t: datetime
    deaths: int | None
    injuries: int | None
    total_deaths: int | None
    total_injuries: int | None
    verification_status: str | None
    duplicate_flag: bool


@dataclass
class ClusterPlan:
    canonical: IncidentRow
    members: list[IncidentRow]
    pair_scores: list[tuple[UUID, UUID, float]] = field(default_factory=list)
    is_nabatiyeh_example: bool = False

    @property
    def size(self) -> int:
        return len(self.members)


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[UUID, UUID] = {}

    def add(self, x: UUID) -> None:
        self.parent.setdefault(x, x)

    def find(self, x: UUID) -> UUID:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: UUID, b: UUID) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _event_ts(row: Any) -> datetime:
    t = row.t
    if t.tzinfo is None:
        return t
    return t


def fetch_candidate_incidents(db: Session, *, lookback_days: int) -> list[IncidentRow]:
    cutoff = datetime.now().astimezone() - timedelta(days=lookback_days)
    rows = db.execute(
        text(
            """
            SELECT
              i.id,
              i.raw_message_id,
              i.village_id,
              COALESCE(v.acs_name, v.ref_name_en, v.ref_name_ar, '?') AS village_name,
              i.condition_id,
              i.khabar,
              i.event_date,
              COALESCE(r.message_datetime, r.received_at, i.created_at) AS t,
              i.deaths,
              i.injuries,
              i.total_deaths,
              i.total_injuries,
              i.verification_status,
              i.duplicate_flag
            FROM incidents i
            JOIN villages v ON v.id = i.village_id
            LEFT JOIN raw_messages r ON r.id = i.raw_message_id
            WHERE i.is_deleted = false
              AND i.khabar IS NOT NULL
              AND i.village_id IS NOT NULL
              AND i.condition_id IS NOT NULL
              AND COALESCE(r.message_datetime, r.received_at, i.created_at)
                  >= :cutoff
            ORDER BY t ASC, i.id ASC
            """
        ),
        {"cutoff": cutoff},
    ).mappings().all()
    return [
        IncidentRow(
            id=row["id"],
            raw_message_id=row["raw_message_id"],
            village_id=row["village_id"],
            village_name=row["village_name"],
            condition_id=row["condition_id"],
            khabar=row["khabar"] or "",
            event_date=row["event_date"],
            t=_event_ts(row),
            deaths=row["deaths"],
            injuries=row["injuries"],
            total_deaths=row["total_deaths"],
            total_injuries=row["total_injuries"],
            verification_status=row["verification_status"],
            duplicate_flag=bool(row["duplicate_flag"]),
        )
        for row in rows
    ]


def _word_similarity(db: Session, a: str, b: str) -> float:
    score = db.execute(
        select(
            func.word_similarity(
                normalize_arabic_sql(literal(a)),
                normalize_arabic_sql(literal(b)),
            )
        )
    ).scalar()
    return float(score or 0.0)


def build_clusters(
    db: Session,
    incidents: list[IncidentRow],
    *,
    gap_mid_seconds: float,
    text_min: float,
) -> list[ClusterPlan]:
    # Multi-village materializations (one raw_message → many incidents) are
    # intentional. Only auto-merge rows whose raw_message produced a single
    # active incident — the Part 1c failure mode (one event, one mention,
    # wrong village_id across outlets).
    rm_counts: dict[int, int] = defaultdict(int)
    for inc in incidents:
        if inc.raw_message_id is not None:
            rm_counts[inc.raw_message_id] += 1
    single_village_rms = {
        rm for rm, count in rm_counts.items() if count == 1
    }

    by_condition: dict[int, list[IncidentRow]] = defaultdict(list)
    for inc in incidents:
        if inc.raw_message_id not in single_village_rms:
            continue
        by_condition[inc.condition_id].append(inc)

    uf = UnionFind()
    pair_scores: dict[tuple[UUID, UUID], float] = {}
    by_id = {inc.id: inc for inc in incidents if inc.raw_message_id in single_village_rms}

    for _cid, group in by_condition.items():
        group = sorted(group, key=lambda r: (r.t, r.id))
        for i, a in enumerate(group):
            uf.add(a.id)
            for b in group[i + 1 :]:
                gap = abs((a.t - b.t).total_seconds())
                if gap > gap_mid_seconds:
                    break
                if a.raw_message_id == b.raw_message_id:
                    continue
                if a.village_id == b.village_id:
                    continue
                sim_ab = _word_similarity(db, a.khabar, b.khabar)
                sim_ba = _word_similarity(db, b.khabar, a.khabar)
                sim = max(sim_ab, sim_ba)
                if sim < text_min:
                    continue
                uf.add(b.id)
                uf.union(a.id, b.id)
                key = (a.id, b.id) if a.id < b.id else (b.id, a.id)
                pair_scores[key] = max(pair_scores.get(key, 0.0), sim)

    roots: dict[UUID, list[IncidentRow]] = defaultdict(list)
    for inc_id, inc in by_id.items():
        if inc_id not in uf.parent:
            continue
        roots[uf.find(inc_id)].append(inc)

    plans: list[ClusterPlan] = []
    for members in roots.values():
        if len(members) < 2:
            continue
        members_sorted = sorted(members, key=lambda r: (r.t, r.id))
        canonical = members_sorted[0]
        scores = [
            (a, b, s)
            for (a, b), s in pair_scores.items()
            if a in {m.id for m in members} and b in {m.id for m in members}
        ]
        raw_ids = {m.raw_message_id for m in members if m.raw_message_id}
        plans.append(
            ClusterPlan(
                canonical=canonical,
                members=members_sorted,
                pair_scores=scores,
                is_nabatiyeh_example=bool(raw_ids & NABATIYEH_CLUSTER_RAW_IDS),
            )
        )
    plans.sort(key=lambda p: (-p.size, p.canonical.t))
    return plans


def _snip(text_value: str, n: int = 100) -> str:
    one = " ".join((text_value or "").split())
    return one if len(one) <= n else one[: n - 1] + "…"


def print_summary(plans: list[ClusterPlan], *, text_min: float, gap_mid: float) -> None:
    total_members = sum(p.size for p in plans)
    to_merge = sum(p.size - 1 for p in plans)
    print(
        f"cross-village clusters (sim>={text_min}, gap<={gap_mid:.0f}s, "
        f"lookback={LOOKBACK_DAYS}d): {len(plans)}"
    )
    print(f"  incidents involved: {total_members}")
    print(f"  would soft-delete (merge into canonical): {to_merge}")
    nab = [p for p in plans if p.is_nabatiyeh_example]
    if nab:
        print(f"  Nabatiyeh/maslakh motivating clusters: {len(nab)}")


def print_examples(plans: list[ClusterPlan], *, limit: int) -> None:
    # Always surface Nabatiyeh cluster(s) first, then largest others.
    ordered = sorted(
        plans,
        key=lambda p: (not p.is_nabatiyeh_example, -p.size, p.canonical.t),
    )
    shown = 0
    for plan in ordered:
        if shown >= limit:
            break
        shown += 1
        tag = " [NABATIYEH/MASLAKH EXAMPLE]" if plan.is_nabatiyeh_example else ""
        print()
        print(f"=== cluster {shown} size={plan.size}{tag} ===")
        print(
            f"  CANONICAL keep id={plan.canonical.id} "
            f"rm={plan.canonical.raw_message_id} "
            f"village={plan.canonical.village_name}({plan.canonical.village_id}) "
            f"t={plan.canonical.t.isoformat()} "
            f"status={plan.canonical.verification_status}"
        )
        print(f"    khabar: {_snip(plan.canonical.khabar, 120)}")
        for member in plan.members[1:]:
            print(
                f"  MERGE→soft-delete id={member.id} "
                f"rm={member.raw_message_id} "
                f"village={member.village_name}({member.village_id}) "
                f"t={member.t.isoformat()} "
                f"status={member.verification_status}"
            )
            print(f"    khabar: {_snip(member.khabar, 120)}")
        if plan.pair_scores:
            top = sorted(plan.pair_scores, key=lambda x: -x[2])[:5]
            print("  top pair scores:")
            for a, b, s in top:
                print(f"    {a} ↔ {b}  sim={s:.4f}")


def apply_cluster(db: Session, plan: ClusterPlan) -> int:
    """Merge members into canonical via IncidentMergeService; soft-delete rest."""
    repo = IncidentRepository(db)
    merge_service = IncidentMergeService(repo)
    canonical = db.get(Incident, plan.canonical.id)
    if canonical is None or canonical.is_deleted:
        return 0

    merged = 0
    for member in plan.members[1:]:
        dupe = db.get(Incident, member.id)
        if dupe is None or dupe.is_deleted:
            continue
        sim = 0.0
        for a, b, s in plan.pair_scores:
            if {a, b} == {canonical.id, dupe.id} or dupe.id in (a, b):
                sim = max(sim, s)

        merge_service.merge(
            existing=canonical,
            new_candidate_data={
                "deaths": dupe.deaths,
                "injuries": dupe.injuries,
                "total_deaths": dupe.total_deaths,
                "total_injuries": dupe.total_injuries,
                "khabar": dupe.khabar,
                "origin_villages": [],
                "mapped_fields": {},
                "casualty_transitions": [],
            },
            raw_message_id=dupe.raw_message_id or 0,
        )
        repo.redirect_pending_duplicate_matches(
            retired_incident=dupe,
            canonical_incident=canonical,
        )
        db.add(
            DuplicateMatch(
                incident_id=dupe.id,
                matched_incident_id=canonical.id,
                match_type=MatchType.soft,
                similarity_score=sim or None,
                status=MatchStatus.confirmed_duplicate,
            )
        )
        dupe.is_deleted = True
        dupe.duplicate_flag = False
        db.add(dupe)
        merged += 1

    canonical.duplicate_flag = False
    db.add(canonical)
    db.commit()
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run / apply cross-village duplicate cluster cleanup."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply merges + soft-deletes (default is dry-run).",
    )
    parser.add_argument(
        "--examples",
        type=int,
        default=8,
        help="How many cluster before/after examples to print (default 8).",
    )
    parser.add_argument(
        "--text-min",
        type=float,
        default=None,
        help=(
            "Override cross-village text similarity floor "
            "(default: settings dedup_cross_village_text_min=0.87)."
        ),
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=LOOKBACK_DAYS,
        help=f"Incident lookback window (default {LOOKBACK_DAYS}).",
    )
    args = parser.parse_args()

    cfg = DuplicateComparisonConfig.from_settings()
    text_min = (
        float(args.text_min)
        if args.text_min is not None
        else cfg.cross_village_text_min
    )
    db = _session()
    try:
        incidents = fetch_candidate_incidents(db, lookback_days=args.lookback_days)
        plans = build_clusters(
            db,
            incidents,
            gap_mid_seconds=cfg.gap_mid_seconds,
            text_min=text_min,
        )
        print_summary(
            plans,
            text_min=text_min,
            gap_mid=cfg.gap_mid_seconds,
        )
        print_examples(plans, limit=max(1, args.examples))

        if not args.apply:
            print()
            print("Dry-run only. Re-run with --apply after review to merge.")
            print(
                "Note: Nabatiyeh/maslakh Sep-7 cluster often scores 0.68–0.86 "
                "pairwise — below the 0.87 Part 1c floor — so it may be absent "
                "at default settings. Try --text-min 0.80 for a wider dry-run "
                "review of that event (still no --apply until approved)."
            )
            return

        total = 0
        for plan in plans:
            total += apply_cluster(db, plan)
        print()
        print(f"Applied: soft-deleted {total} incidents across {len(plans)} clusters.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
