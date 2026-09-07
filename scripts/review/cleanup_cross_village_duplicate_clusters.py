#!/usr/bin/env python
"""Retroactive cleanup of cross-village near-duplicate incidents.

Part 1c's live backstop only flags *new* messages. Incidents materialized
before that landing are still on the board. This script:

1. Finds live pairs matching the Part 1c coarse filter (same condition,
   different village, ≤30 min on ``event_date + event_time``,
   unnormalized ``word_similarity(khabar) >= 0.87``).
2. Re-scores every coarse pair through
   ``DuplicateComparisonService.compare(..., village_match_uncertain=True)``.
3. Merge is **not** "every possible_duplicate pair". Live Part 1c never
   auto-merges cross-village hits (human review only), and the 0.87 net
   also catches templated distinct events (Houla vs Mansouri) plus
   daily-summary copy. Cleanup merges only when the 5 live location
   aliases say both rows should have been the **same parent village**
   — the actual pre-fix failure mode (Al-Maslakh → Masqa/Douair/Zibdine).

   Alias-same-parent pairs below 0.87 are included too: after the alias
   fix they would have been same-village and scored on the standard
   (lower) threshold. Outlet copy of the car-strike is often 0.3–0.8,
   so requiring 0.87 would leave most of the Nabatiyeh fan-out in place.

Canonical rule (uniform): earliest ``event_date+event_time`` wins; if two
candidates are within ``dedup_fastpath_gap_near_seconds`` (2 minutes),
prefer ``channel_trust_tiers`` official > trusted > detail; then earlier
``message_datetime``; then smaller incident id.

STANDING CONVENTION: dry-run by default. Do not ``--apply`` without Najdi
review. No hard deletes. Does not re-seed neighborhood aliases.

Usage:
  python scripts/review/cleanup_cross_village_duplicate_clusters.py
  python scripts/review/cleanup_cross_village_duplicate_clusters.py --apply
  python scripts/review/cleanup_cross_village_duplicate_clusters.py --apply --correct-canonical-village
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.news.models import (
    ChannelTrustTier,
    Condition,
    DuplicateMatch,
    Incident,
    IncidentDetail,
    IncidentUpdate,
    MatchStatus,
    MatchType,
    TrustTier,
    UpdateAction,
    Village,
)
from app.news.models.raw_message import RawMessage
from app.news.models.village_location_alias import VillageLocationAlias
from app.news.repositories.incident_repository import IncidentRepository
from app.news.repositories.village_repository import VillageRepository
from app.news.services.clustering.clustering_service import (
    TRUST_TIER_RANK,
    UNKNOWN_TRUST_TIER_RANK,
)
from app.news.services.dedup.duplicate_comparison_service import (
    DuplicateComparisonService,
    Verdict,
)
from app.news.services.dedup.incident_merge_service import IncidentMergeService

DEFAULT_DATABASE_URL = "postgresql+psycopg2://postgres:secret@localhost:5432/war_news_dev"
MASLAKH_HINTS = ("المسلخ", "حي المسلخ")
# Neighborhood/compound aliases that identify one event even when outlet
# copy scores below the same-village text bar. Bare النبطية / مدينة النبطية
# are too broad (any city-center event in a 30-minute window).
SPECIFIC_ALIAS_BOOST = frozenset({"حي المسلخ", "المسلخ", "محيط النبطية الفوقا"})
NABATIYEH_WRONG_OR_RELATED_VILLAGE_IDS = frozenset(
    {543, 995, 976, 1152, 1153, 1529}
)


def _session() -> Session:
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    if "@db:" in url and not Path("/.dockerenv").exists():
        url = url.replace("@db:", "@localhost:")
    return sessionmaker(bind=create_engine(url))()


@dataclass
class LiveAlias:
    alias_text: str
    alias_normalized: str
    village_id: int
    village_name: str


@dataclass
class IncidentRow:
    id: UUID
    raw_message_id: int | None
    village_id: int
    village_name: str
    condition_id: int
    condition_name: str
    khabar: str
    event_date: Any
    event_time: Any
    event_dt: datetime
    message_datetime: datetime | None
    deaths: int | None
    injuries: int | None
    total_deaths: int | None
    total_injuries: int | None
    verification_status: str | None
    duplicate_flag: bool
    channel: str | None
    trust_tier: str | None
    trust_rank: int
    raw_village_texts: list[str]
    alias_village_id: int | None
    alias_village_name: str | None
    alias_matched_texts: tuple[str, ...]
    alias_multi: bool
    rm_incident_count: int


@dataclass
class PairEval:
    id_a: UUID
    id_b: UUID
    gap_seconds: float
    sim_raw: float
    sim_norm: float | None
    emb_sim: float | None
    verdict: Verdict
    similarity_method: str
    similarity_score: float
    village_match_uncertain: bool
    shared_alias_parent: int | None
    merge_eligible: bool
    merge_reason: str
    source: str  # "coarse_0.87" | "alias_parent"


@dataclass
class ClusterPlan:
    canonical: IncidentRow
    members: list[IncidentRow]
    pairs: list[PairEval] = field(default_factory=list)
    is_nabatiyeh_example: bool = False
    proposed_village_id: int | None = None
    proposed_village_name: str | None = None
    village_correction_needed: bool = False
    village_correction_reason: str = ""

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


def _event_dt(event_date: Any, event_time: Any) -> datetime:
    return datetime.combine(event_date, event_time or time(0, 0))


def _village_texts_for_incident(
    match_result: dict[str, Any] | None,
    village_id: int,
) -> list[str]:
    if not isinstance(match_result, dict):
        return []
    matches = match_result.get("village_matches")
    if not isinstance(matches, list):
        raw = match_result.get("raw_village_text")
        matched_id = match_result.get("matched_village_id")
        if isinstance(raw, str) and raw.strip() and matched_id == village_id:
            return [raw.strip()]
        return []
    texts: list[str] = []
    for item in matches:
        if not isinstance(item, dict):
            continue
        if item.get("matched_village_id") != village_id:
            continue
        raw = item.get("raw_village_text")
        if isinstance(raw, str) and raw.strip() and raw.strip() not in texts:
            texts.append(raw.strip())
    return texts


def _channel_name(raw: RawMessage | None) -> str | None:
    if raw is None:
        return None
    for candidate in (raw.origin_account, raw.source_name, raw.source_platform):
        if candidate:
            return str(candidate)
    return None


def _pair_sim_sql() -> str:
    return """
      word_similarity(a.khabar, b.khabar) AS sim_raw,
      word_similarity(
        btrim(regexp_replace(btrim(btrim(
          replace(translate(
            regexp_replace(a.khabar, '[\u064b-\u0652\u0640]', '', 'g'),
            'أإآٱة', 'ااااه'), 'ى', 'ي')),
          '،.؛!؟"'''), '\\s+', ' ', 'g')),
        btrim(regexp_replace(btrim(btrim(
          replace(translate(
            regexp_replace(b.khabar, '[\u064b-\u0652\u0640]', '', 'g'),
            'أإآٱة', 'ااااه'), 'ى', 'ي')),
          '،.؛!؟"'''), '\\s+', ' ', 'g'))
      ) AS sim_norm,
      CASE
        WHEN a.khabar_embedding IS NOT NULL
         AND b.khabar_embedding IS NOT NULL
        THEN 1 - (a.khabar_embedding <=> b.khabar_embedding)
        ELSE NULL
      END AS emb_sim,
      ABS(EXTRACT(EPOCH FROM (
            (a.event_date + COALESCE(a.event_time, TIME '00:00'))
          - (b.event_date + COALESCE(b.event_time, TIME '00:00'))
          ))) AS gap_seconds
    """


def fetch_coarse_pairs(db: Session, *, gap_mid_seconds: float, text_min: float) -> list[dict[str, Any]]:
    """Step 1: live pairs matching the Part 1c coarse filter.

    Timestamp-fixed form of the prompt SQL: ``event_date`` is a date, so the
    literal ``EXTRACT(EPOCH FROM (a.event_date - b.event_date))`` errors.
    Production gap uses ``event_date + COALESCE(event_time, 00:00)``.
    """
    return list(
        db.execute(
            text(
                f"""
                SELECT a.id AS id_a, b.id AS id_b,
                {_pair_sim_sql()}
                FROM incidents a
                JOIN incidents b ON a.id < b.id
                  AND a.condition_id = b.condition_id
                  AND a.village_id IS DISTINCT FROM b.village_id
                  AND a.is_deleted = false AND b.is_deleted = false
                  AND a.village_id IS NOT NULL AND b.village_id IS NOT NULL
                  AND a.condition_id IS NOT NULL AND b.condition_id IS NOT NULL
                  AND ABS(EXTRACT(EPOCH FROM (
                        (a.event_date + COALESCE(a.event_time, TIME '00:00'))
                      - (b.event_date + COALESCE(b.event_time, TIME '00:00'))
                      ))) <= :gap_mid
                WHERE word_similarity(a.khabar, b.khabar) >= :text_min
                ORDER BY sim_raw DESC, a.id, b.id
                """
            ),
            {"gap_mid": gap_mid_seconds, "text_min": text_min},
        ).mappings().all()
    )


def fetch_alias_mention_ids(db: Session) -> set[UUID]:
    rows = db.execute(
        text(
            """
            SELECT DISTINCT i.id
            FROM incidents i
            LEFT JOIN raw_messages r ON r.id = i.raw_message_id
            JOIN village_location_aliases a ON a.is_active = true
            WHERE i.is_deleted = false
              AND i.village_id IS NOT NULL
              AND i.condition_id IS NOT NULL
              AND (
                position(a.alias_text in coalesce(i.khabar, '')) > 0
                OR position(a.alias_text in coalesce(r.match_result::text, '')) > 0
              )
            """
        )
    ).all()
    return {row[0] for row in rows}


def fetch_pair_metrics(db: Session, pairs: list[tuple[UUID, UUID]]) -> dict[tuple[UUID, UUID], dict[str, Any]]:
    if not pairs:
        return {}
    ids_a = [str(a) for a, _ in pairs]
    ids_b = [str(b) for _, b in pairs]
    rows = db.execute(
        text(
            f"""
            WITH p AS (
              SELECT unnest(CAST(:ids_a AS uuid[])) AS id_a,
                     unnest(CAST(:ids_b AS uuid[])) AS id_b
            )
            SELECT p.id_a, p.id_b,
            {_pair_sim_sql()}
            FROM p
            JOIN incidents a ON a.id = p.id_a
            JOIN incidents b ON b.id = p.id_b
            """
        ),
        {"ids_a": ids_a, "ids_b": ids_b},
    ).mappings().all()
    return {(row["id_a"], row["id_b"]): dict(row) for row in rows}


def load_live_aliases(db: Session) -> list[LiveAlias]:
    rows = db.execute(
        select(VillageLocationAlias, Village)
        .join(Village, Village.id == VillageLocationAlias.village_id)
        .where(VillageLocationAlias.is_active.is_(True))
    ).all()
    aliases = [
        LiveAlias(
            alias_text=alias.alias_text,
            alias_normalized=alias.alias_normalized,
            village_id=village.id,
            village_name=village.acs_name or village.ref_name_en or village.ref_name_ar or "?",
        )
        for alias, village in rows
    ]
    aliases.sort(key=lambda a: len(a.alias_text), reverse=True)
    return aliases


def resolve_incident_alias(
    *,
    extracted: list[str],
    khabar: str,
    aliases: list[LiveAlias],
    village_repo: VillageRepository,
) -> tuple[int | None, str | None, tuple[str, ...], bool]:
    """Resolve using extracted village text only; upgrade to a *longer* live alias.

    Full-khabar substring search is intentionally not used for the initial hit
    — daily recaps mention النبطية while being about Houla / Mansouri.
    """
    hits: dict[int, str] = {}
    matched_texts: list[str] = []

    def remember(alias: LiveAlias) -> None:
        hits[alias.village_id] = alias.village_name
        if alias.alias_text not in matched_texts:
            matched_texts.append(alias.alias_text)

    for raw_text in extracted:
        exact = village_repo.resolve_alias(raw_text)
        if exact is not None:
            village, _conf = exact
            # Prefer a longer alias in khabar that contains this extracted span.
            upgraded = None
            for alias in aliases:
                if alias.alias_text in khabar and raw_text in alias.alias_text:
                    if upgraded is None or len(alias.alias_text) > len(upgraded.alias_text):
                        upgraded = alias
            if upgraded is not None:
                remember(upgraded)
            else:
                hits[village.id] = village.acs_name or village.ref_name_en or village.ref_name_ar or "?"
                if raw_text not in matched_texts:
                    matched_texts.append(raw_text)
            continue
        # Extracted text is not an exact alias; allow upgrade if a longer live
        # alias in the khabar contains the extracted span (النبطية → مدينة النبطية).
        for alias in aliases:
            if alias.alias_text in khabar and raw_text in alias.alias_text:
                remember(alias)
                break

    if len(hits) > 1:
        return None, None, tuple(matched_texts), True
    if len(hits) == 1:
        vid, name = next(iter(hits.items()))
        return vid, name, tuple(matched_texts), False
    return None, None, tuple(matched_texts), False


def load_incidents(
    db: Session,
    ids: set[UUID],
    *,
    aliases: list[LiveAlias],
) -> dict[UUID, IncidentRow]:
    if not ids:
        return {}
    incidents = list(db.scalars(select(Incident).where(Incident.id.in_(ids))).all())
    village_ids = {i.village_id for i in incidents if i.village_id is not None}
    villages = {
        v.id: v
        for v in db.scalars(select(Village).where(Village.id.in_(village_ids))).all()
    }
    condition_ids = {i.condition_id for i in incidents if i.condition_id is not None}
    conditions = {
        c.id: c
        for c in db.scalars(select(Condition).where(Condition.id.in_(condition_ids))).all()
    }
    raw_ids = {i.raw_message_id for i in incidents if i.raw_message_id is not None}
    raws = {
        r.id: r
        for r in db.scalars(select(RawMessage).where(RawMessage.id.in_(raw_ids))).all()
    }
    rm_counts_rows = db.execute(
        text(
            """
            SELECT raw_message_id, COUNT(*) AS n
            FROM incidents
            WHERE is_deleted = false AND raw_message_id IS NOT NULL
            GROUP BY raw_message_id
            """
        )
    ).mappings().all()
    rm_counts = {int(row["raw_message_id"]): int(row["n"]) for row in rm_counts_rows}
    tiers = {row.channel_name: row.tier for row in db.scalars(select(ChannelTrustTier)).all()}
    village_repo = VillageRepository(db)

    out: dict[UUID, IncidentRow] = {}
    for inc in incidents:
        village = villages.get(inc.village_id) if inc.village_id is not None else None
        condition = conditions.get(inc.condition_id) if inc.condition_id is not None else None
        raw = raws.get(inc.raw_message_id) if inc.raw_message_id is not None else None
        channel = _channel_name(raw)
        tier = tiers.get(channel) if channel else None
        trust_rank = (
            TRUST_TIER_RANK[tier] if isinstance(tier, TrustTier) else UNKNOWN_TRUST_TIER_RANK
        )
        texts = _village_texts_for_incident(
            raw.match_result if raw is not None else None,
            inc.village_id or 0,
        )
        alias_id, alias_name, matched, multi = resolve_incident_alias(
            extracted=texts,
            khabar=inc.khabar or "",
            aliases=aliases,
            village_repo=village_repo,
        )
        out[inc.id] = IncidentRow(
            id=inc.id,
            raw_message_id=inc.raw_message_id,
            village_id=inc.village_id or 0,
            village_name=(
                (village.acs_name if village else None)
                or (village.ref_name_en if village else None)
                or (village.ref_name_ar if village else None)
                or "?"
            ),
            condition_id=inc.condition_id or 0,
            condition_name=(
                (condition.action_en if condition else None)
                or (condition.action_ar if condition else None)
                or "?"
            ),
            khabar=inc.khabar or "",
            event_date=inc.event_date,
            event_time=inc.event_time,
            event_dt=_event_dt(inc.event_date, inc.event_time),
            message_datetime=raw.message_datetime if raw is not None else None,
            deaths=inc.deaths,
            injuries=inc.injuries,
            total_deaths=inc.total_deaths,
            total_injuries=inc.total_injuries,
            verification_status=inc.verification_status,
            duplicate_flag=bool(inc.duplicate_flag),
            channel=channel,
            trust_tier=tier.value if isinstance(tier, TrustTier) else None,
            trust_rank=trust_rank,
            raw_village_texts=texts,
            alias_village_id=alias_id,
            alias_village_name=alias_name,
            alias_matched_texts=matched,
            alias_multi=multi,
            rm_incident_count=rm_counts.get(inc.raw_message_id or -1, 0),
        )
    return out


def _merge_decision(
    left: IncidentRow,
    right: IncidentRow,
    *,
    result_verdict: Verdict,
    gap_mid: float,
    gap_seconds: float,
) -> tuple[bool, str, int | None]:
    if gap_seconds > gap_mid:
        return False, "gap_over_30min", None
    if left.alias_multi or right.alias_multi:
        return False, "multi_alias_on_one_side", None
    if (
        left.alias_village_id is None
        or right.alias_village_id is None
        or left.alias_village_id != right.alias_village_id
    ):
        return False, "no_shared_live_alias_parent", None
    if left.condition_id != right.condition_id:
        return False, "condition_mismatch", None
    parent = left.alias_village_id
    if left.village_id == parent and right.village_id == parent:
        return False, "both_already_on_correct_village", None
    specific = (
        set(left.alias_matched_texts) & set(right.alias_matched_texts) & SPECIFIC_ALIAS_BOOST
    )
    if result_verdict in ("possible_duplicate", "high_confidence_duplicate"):
        return True, f"shared_alias_parent={parent} + service_{result_verdict}", parent
    token_ok = bool(specific) and (
        left.raw_message_id == right.raw_message_id
        or (left.rm_incident_count == 1 and right.rm_incident_count == 1)
    )
    if token_ok:
        return True, f"shared_alias_parent={parent} + shared_token={sorted(specific)}", parent
    return False, "shared_alias_but_below_service_threshold_and_no_specific_token", parent


def classify_coarse_pairs(
    rows: list[dict[str, Any]],
    incidents: dict[UUID, IncidentRow],
    comparison: DuplicateComparisonService,
) -> list[PairEval]:
    out: list[PairEval] = []
    gap_mid = comparison.config.gap_mid_seconds
    for row in rows:
        id_a = row["id_a"]
        id_b = row["id_b"]
        gap = float(row["gap_seconds"] or 0.0)
        sim_raw = float(row["sim_raw"] or 0.0)
        sim_norm = None if row["sim_norm"] is None else float(row["sim_norm"])
        emb_sim = None if row["emb_sim"] is None else float(row["emb_sim"])
        result = comparison.compare(
            time_gap_seconds=gap,
            text_similarity=sim_norm,
            embedding_similarity=emb_sim,
            village_match_uncertain=True,
        )
        left = incidents[id_a]
        right = incidents[id_b]
        eligible, reason, parent = _merge_decision(
            left, right, result_verdict=result.verdict, gap_mid=gap_mid, gap_seconds=gap
        )
        out.append(
            PairEval(
                id_a=id_a,
                id_b=id_b,
                gap_seconds=gap,
                sim_raw=sim_raw,
                sim_norm=sim_norm,
                emb_sim=emb_sim,
                verdict=result.verdict,
                similarity_method=result.similarity_method,
                similarity_score=result.similarity_score,
                village_match_uncertain=True,
                shared_alias_parent=parent,
                merge_eligible=eligible,
                merge_reason=reason,
                source="coarse_0.87",
            )
        )
    return out


def classify_alias_pairs(
    db: Session,
    incidents: dict[UUID, IncidentRow],
    comparison: DuplicateComparisonService,
    *,
    already: set[tuple[UUID, UUID]],
) -> list[PairEval]:
    gap_mid = comparison.config.gap_mid_seconds
    by_key: dict[tuple[int, int], list[IncidentRow]] = defaultdict(list)
    for row in incidents.values():
        if row.alias_village_id is None or row.alias_multi:
            continue
        by_key[(row.alias_village_id, row.condition_id)].append(row)

    candidate_pairs: list[tuple[UUID, UUID]] = []
    for group in by_key.values():
        group = sorted(group, key=lambda r: (r.event_dt, str(r.id)))
        for i, left in enumerate(group):
            for right in group[i + 1 :]:
                gap = abs((left.event_dt - right.event_dt).total_seconds())
                if gap > gap_mid:
                    break
                key = (left.id, right.id) if left.id < right.id else (right.id, left.id)
                if key in already:
                    continue
                candidate_pairs.append(key)

    metrics = fetch_pair_metrics(db, candidate_pairs)
    out: list[PairEval] = []
    for id_a, id_b in candidate_pairs:
        row = metrics.get((id_a, id_b)) or metrics.get((id_b, id_a))
        if row is None:
            continue
        gap = float(row["gap_seconds"] or 0.0)
        sim_raw = float(row["sim_raw"] or 0.0)
        sim_norm = None if row["sim_norm"] is None else float(row["sim_norm"])
        emb_sim = None if row["emb_sim"] is None else float(row["emb_sim"])
        # After alias fix these are same-village, so use the standard path.
        result = comparison.compare(
            time_gap_seconds=gap,
            text_similarity=sim_norm,
            embedding_similarity=emb_sim,
            village_match_uncertain=False,
        )
        left = incidents[id_a]
        right = incidents[id_b]
        eligible, reason, parent = _merge_decision(
            left, right, result_verdict=result.verdict, gap_mid=gap_mid, gap_seconds=gap
        )
        out.append(
            PairEval(
                id_a=id_a,
                id_b=id_b,
                gap_seconds=gap,
                sim_raw=sim_raw,
                sim_norm=sim_norm,
                emb_sim=emb_sim,
                verdict=result.verdict,
                similarity_method=result.similarity_method,
                similarity_score=result.similarity_score,
                village_match_uncertain=False,
                shared_alias_parent=parent,
                merge_eligible=eligible,
                merge_reason=reason,
                source="alias_parent",
            )
        )
    return out


def _is_nabatiyeh_member(row: IncidentRow) -> bool:
    blob = " ".join([row.khabar, *row.raw_village_texts])
    return any(hint in blob for hint in MASLAKH_HINTS) and (
        row.alias_village_id == 1152
        or row.village_id in NABATIYEH_WRONG_OR_RELATED_VILLAGE_IDS
    )


def _canonical_sort_key(row: IncidentRow, *, near_seconds: float, earliest: datetime) -> tuple:
    close = abs((row.event_dt - earliest).total_seconds()) <= near_seconds
    if close:
        return (0, row.trust_rank, row.event_dt, row.message_datetime or row.event_dt, str(row.id))
    return (1, row.event_dt, row.trust_rank, row.message_datetime or row.event_dt, str(row.id))


def pick_canonical(members: list[IncidentRow], *, near_seconds: float) -> IncidentRow:
    earliest = min(m.event_dt for m in members)
    return min(members, key=lambda r: _canonical_sort_key(r, near_seconds=near_seconds, earliest=earliest))


def _alias_consensus(members: list[IncidentRow]) -> tuple[int | None, str | None, str]:
    votes: dict[int, list[IncidentRow]] = defaultdict(list)
    for member in members:
        if member.alias_village_id is not None and not member.alias_multi:
            votes[member.alias_village_id].append(member)
    if not votes:
        return None, None, "no unique live alias parent"
    best_id, best_members = max(votes.items(), key=lambda item: len(item[1]))
    name = best_members[0].alias_village_name
    if len(votes) > 1:
        parts = ", ".join(
            f"{vid}×{len(rows)} ({rows[0].alias_village_name})"
            for vid, rows in sorted(votes.items(), key=lambda item: -len(item[1]))
        )
        return best_id, name, f"split alias votes: {parts}"
    return best_id, name, f"unanimous live alias → {name} ({best_id})"


def build_clusters(
    pairs: list[PairEval],
    incidents: dict[UUID, IncidentRow],
    *,
    near_seconds: float,
) -> list[ClusterPlan]:
    uf = UnionFind()
    eligible = [p for p in pairs if p.merge_eligible]
    for pair in eligible:
        uf.add(pair.id_a)
        uf.add(pair.id_b)
        uf.union(pair.id_a, pair.id_b)

    groups: dict[UUID, list[UUID]] = defaultdict(list)
    for inc_id in uf.parent:
        groups[uf.find(inc_id)].append(inc_id)

    plans: list[ClusterPlan] = []
    for member_ids in groups.values():
        members = [incidents[i] for i in member_ids]
        canonical = pick_canonical(members, near_seconds=near_seconds)
        members_sorted = [canonical] + sorted(
            [m for m in members if m.id != canonical.id],
            key=lambda r: (r.event_dt, str(r.id)),
        )
        member_set = {m.id for m in members_sorted}
        cluster_pairs = [
            p for p in eligible if p.id_a in member_set and p.id_b in member_set
        ]
        proposed_id, proposed_name, reason = _alias_consensus(members_sorted)
        correction_needed = (
            proposed_id is not None and proposed_id != canonical.village_id
        )
        plans.append(
            ClusterPlan(
                canonical=canonical,
                members=members_sorted,
                pairs=cluster_pairs,
                is_nabatiyeh_example=any(_is_nabatiyeh_member(m) for m in members_sorted),
                proposed_village_id=proposed_id,
                proposed_village_name=proposed_name,
                village_correction_needed=correction_needed,
                village_correction_reason=reason,
            )
        )
    plans.sort(key=lambda p: (not p.is_nabatiyeh_example, -p.size, p.canonical.event_dt))
    return plans


def _snip(text_value: str, n: int = 140) -> str:
    one = " ".join((text_value or "").split())
    return one if len(one) <= n else one[: n - 1] + "…"


def _detail_mapped_fields(detail: IncidentDetail | None) -> dict[str, Any]:
    if detail is None:
        return {}
    excluded = {"incident_id"}
    out: dict[str, Any] = {}
    for column in IncidentDetail.__table__.columns:
        if column.name in excluded:
            continue
        value = getattr(detail, column.name)
        if value is None:
            continue
        out[column.name] = value.value if hasattr(value, "value") else value
    return out


def print_summary(
    *,
    coarse_n: int,
    coarse_pairs: list[PairEval],
    alias_pairs: list[PairEval],
    plans: list[ClusterPlan],
    text_min: float,
    gap_mid: float,
) -> None:
    possible = [p for p in coarse_pairs if p.verdict == "possible_duplicate"]
    distinct = [p for p in coarse_pairs if p.verdict == "distinct"]
    coarse_merge = [p for p in possible if p.merge_eligible]
    coarse_leave = [p for p in possible if not p.merge_eligible]
    alias_merge = [p for p in alias_pairs if p.merge_eligible]
    print(
        f"Step 1 coarse pairs (unnormalized word_similarity>={text_min}, "
        f"gap<={gap_mid:.0f}s, different village, same condition): {coarse_n}"
    )
    print("  (literal prompt SQL on date-typed event_date errors in Postgres;")
    print("   this is the production-equivalent timestamp window.)")
    print("Step 3 DuplicateComparisonService:")
    print(f"  coarse pairs → possible_duplicate: {len(possible)}")
    print(f"  coarse pairs → distinct: {len(distinct)}")
    print(f"  of possible_duplicate, shared live alias parent (merge): {len(coarse_merge)}")
    print(f"  of possible_duplicate, no shared alias / other (leave): {len(coarse_leave)}")
    print(
        f"  extra alias-parent pairs below 0.87 scored on same-village path, "
        f"merge-eligible: {len(alias_merge)}"
    )
    to_merge = sum(p.size - 1 for p in plans)
    print(
        f"  merge clusters: {len(plans)} "
        f"(incidents involved={sum(p.size for p in plans)}, "
        f"would soft-delete={to_merge})"
    )
    nab = [p for p in plans if p.is_nabatiyeh_example]
    print(f"  Nabatiyeh/Al-Maslakh clusters: {len(nab)}")
    need_v = [p for p in plans if p.village_correction_needed]
    print(f"  clusters whose canonical village_id looks wrong vs live aliases: {len(need_v)}")


def print_cluster(plan: ClusterPlan, *, index: int) -> None:
    tag = " [NABATIYEH / AL-MASLAKH]" if plan.is_nabatiyeh_example else ""
    print()
    print(f"=== cluster {index} size={plan.size}{tag} ===")
    print("  BEFORE (current fan-out):")
    for member in plan.members:
        role = "CANONICAL keep" if member.id == plan.canonical.id else "MERGE→soft-delete"
        print(
            f"    {role} id={member.id} rm={member.raw_message_id} "
            f"village={member.village_name}({member.village_id}) "
            f"condition={member.condition_name} "
            f"event={member.event_dt.isoformat()} "
            f"channel={member.channel or '—'} tier={member.trust_tier or 'unknown'} "
            f"status={member.verification_status} "
            f"d/i={member.deaths}/{member.injuries}"
        )
        if member.raw_village_texts:
            print(f"      extracted village text: {', '.join(member.raw_village_texts)}")
        if member.alias_village_id is not None:
            print(
                f"      live alias → {member.alias_village_name}"
                f"({member.alias_village_id}) via {member.alias_matched_texts or '()'}"
            )
        print(f"      khabar: {_snip(member.khabar)}")
    print("  AFTER (proposed):")
    print(
        f"    keep id={plan.canonical.id} village={plan.canonical.village_name}"
        f"({plan.canonical.village_id}) "
        f"event={plan.canonical.event_dt.isoformat()} "
        f"channel={plan.canonical.channel or '—'} tier={plan.canonical.trust_tier or 'unknown'}"
    )
    print(
        f"    soft-delete {plan.size - 1} duplicate(s); "
        f"IncidentMergeService.merge + is_deleted=true; "
        f"incident_updates.merged_from provenance"
    )
    if plan.village_correction_needed:
        print(
            f"    VILLAGE CORRECTION NEEDED: canonical currently "
            f"{plan.canonical.village_name}({plan.canonical.village_id}) "
            f"but live aliases say {plan.proposed_village_name}"
            f"({plan.proposed_village_id}). {plan.village_correction_reason}."
        )
        print(
            "    Pass --correct-canonical-village with --apply to set "
            "canonical.village_id after the merge. Plain --apply leaves the "
            "wrong village name on the surviving row."
        )
    else:
        print(f"    village assignment: {plan.village_correction_reason}")
    if plan.pairs:
        top = sorted(plan.pairs, key=lambda p: -p.similarity_score)[:12]
        print("  pair scores (service):")
        for pair in top:
            print(
                f"    {pair.id_a} ↔ {pair.id_b}  "
                f"raw={pair.sim_raw:.4f} norm={pair.sim_norm or 0:.4f} "
                f"emb={('%.4f' % pair.emb_sim) if pair.emb_sim is not None else '—'} "
                f"gap={pair.gap_seconds:.0f}s  verdict={pair.verdict} "
                f"uncertain={pair.village_match_uncertain} "
                f"via={pair.similarity_method} src={pair.source} "
                f"reason={pair.merge_reason}"
            )


def print_left_alone_examples(pairs: list[PairEval], incidents: dict[UUID, IncidentRow], *, limit: int = 6) -> None:
    leave = [p for p in pairs if p.verdict == "possible_duplicate" and not p.merge_eligible]
    if not leave:
        return
    print()
    print(
        f"=== possible_duplicate left alone "
        f"(no shared live alias parent / daily recap / templated distinct; "
        f"{len(leave)} pairs, showing {min(limit, len(leave))}) ==="
    )
    for pair in leave[:limit]:
        a = incidents[pair.id_a]
        b = incidents[pair.id_b]
        print(
            f"  {a.village_name}({a.village_id}) ↔ {b.village_name}({b.village_id}) "
            f"norm={pair.sim_norm or 0:.4f} gap={pair.gap_seconds:.0f}s "
            f"reason={pair.merge_reason}"
        )
        print(f"    a: {_snip(a.khabar, 100)}")
        print(f"    b: {_snip(b.khabar, 100)}")


def print_already_resolved_maslakh(db: Session) -> None:
    rows = db.execute(
        text(
            """
            SELECT i.id, i.raw_message_id, i.village_id, i.is_deleted,
                   COALESCE(v.acs_name, v.ref_name_en, '?') AS village,
                   i.event_date, i.event_time,
                   LEFT(regexp_replace(i.khabar, E'[\\n\\r]+', ' ', 'g'), 100) AS khabar
            FROM incidents i
            JOIN villages v ON v.id = i.village_id
            WHERE i.khabar ILIKE '%المسلخ%'
              AND i.event_date = DATE '2026-09-07'
            ORDER BY i.is_deleted, i.event_time, i.raw_message_id
            """
        )
    ).mappings().all()
    if not rows:
        return
    print()
    print("=== Sep 7 Al-Maslakh car-strike — current DB (including soft-deleted) ===")
    for row in rows:
        state = "ACTIVE" if not row["is_deleted"] else "already soft-deleted"
        print(
            f"  {state} rm={row['raw_message_id']} village={row['village']}"
            f"({row['village_id']}) {row['khabar']}"
        )


def print_maslakh_inventory(incidents: dict[UUID, IncidentRow], plans: list[ClusterPlan]) -> None:
    merged_ids = {m.id for p in plans for m in p.members}
    rows = [
        inc
        for inc in incidents.values()
        if any(hint in inc.khabar for hint in MASLAKH_HINTS)
    ]
    if not rows:
        return
    rows.sort(key=lambda r: (r.event_dt, str(r.id)))
    print()
    print(f"=== Al-Maslakh inventory ({len(rows)} active incidents mentioning المسلخ) ===")
    for inc in rows:
        in_merge = inc.id in merged_ids
        print(
            f"  {'MERGE' if in_merge else 'LEAVE'} rm={inc.raw_message_id} "
            f"id={inc.id} village={inc.village_name}({inc.village_id}) "
            f"cond={inc.condition_name} event={inc.event_dt.isoformat()} "
            f"extracted={inc.raw_village_texts or '—'} "
            f"alias={inc.alias_village_name}({inc.alias_village_id}) "
            f"via={inc.alias_matched_texts or '()'}"
        )
        print(f"    {_snip(inc.khabar, 120)}")


def apply_cluster(
    db: Session,
    plan: ClusterPlan,
    *,
    correct_village: bool,
) -> int:
    repo = IncidentRepository(db)
    merge_service = IncidentMergeService(repo)
    canonical = db.get(Incident, plan.canonical.id)
    if canonical is None or canonical.is_deleted:
        return 0

    merged = 0
    for member in plan.members:
        if member.id == plan.canonical.id:
            continue
        dupe = db.get(Incident, member.id)
        if dupe is None or dupe.is_deleted:
            continue
        detail = db.get(IncidentDetail, dupe.id)
        sim = 0.0
        for pair in plan.pairs:
            if {pair.id_a, pair.id_b} == {canonical.id, dupe.id}:
                sim = max(sim, pair.similarity_score)
        merge_service.merge(
            existing=canonical,
            new_candidate_data={
                "deaths": dupe.deaths,
                "injuries": dupe.injuries,
                "total_deaths": dupe.total_deaths,
                "total_injuries": dupe.total_injuries,
                "khabar": dupe.khabar,
                "origin_villages": [],
                "mapped_fields": _detail_mapped_fields(detail),
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

    if (
        correct_village
        and plan.village_correction_needed
        and plan.proposed_village_id is not None
        and canonical.village_id != plan.proposed_village_id
    ):
        old_vid = canonical.village_id
        db.add(
            IncidentUpdate(
                incident_id=canonical.id,
                action=UpdateAction.edit,
                old_values={"village_id": old_vid},
                new_values={
                    "village_id": plan.proposed_village_id,
                    "reason": "cross_village_cleanup_alias_correction",
                    "note": plan.village_correction_reason,
                },
                performed_by=None,
            )
        )
        canonical.village_id = plan.proposed_village_id

    canonical.duplicate_flag = False
    db.add(canonical)
    db.commit()
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run / apply cross-village duplicate incident cleanup."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply merges + soft-deletes (default is dry-run).",
    )
    parser.add_argument(
        "--correct-canonical-village",
        action="store_true",
        help="After merge, set canonical.village_id from live alias consensus.",
    )
    parser.add_argument(
        "--leave-examples",
        type=int,
        default=6,
        help="How many left-alone possible_duplicate examples to print.",
    )
    args = parser.parse_args()

    comparison = DuplicateComparisonService()
    cfg = comparison.config
    db = _session()
    try:
        aliases = load_live_aliases(db)
        coarse_rows = fetch_coarse_pairs(
            db,
            gap_mid_seconds=cfg.gap_mid_seconds,
            text_min=cfg.cross_village_text_min,
        )
        ids: set[UUID] = set()
        for row in coarse_rows:
            ids.add(row["id_a"])
            ids.add(row["id_b"])
        ids |= fetch_alias_mention_ids(db)
        incidents = load_incidents(db, ids, aliases=aliases)
        coarse_pairs = classify_coarse_pairs(coarse_rows, incidents, comparison)
        already = {
            (p.id_a, p.id_b) if p.id_a < p.id_b else (p.id_b, p.id_a)
            for p in coarse_pairs
        }
        alias_pairs = classify_alias_pairs(
            db, incidents, comparison, already=already
        )
        all_pairs = coarse_pairs + alias_pairs
        plans = build_clusters(all_pairs, incidents, near_seconds=cfg.gap_near_seconds)

        print(f"Live aliases in play: {len(aliases)}")
        for alias in aliases:
            print(f"  {alias.alias_text!r} → {alias.village_name}({alias.village_id})")
        print()
        print_summary(
            coarse_n=len(coarse_rows),
            coarse_pairs=coarse_pairs,
            alias_pairs=alias_pairs,
            plans=plans,
            text_min=cfg.cross_village_text_min,
            gap_mid=cfg.gap_mid_seconds,
        )
        print_left_alone_examples(
            coarse_pairs, incidents, limit=max(0, args.leave_examples)
        )
        print_already_resolved_maslakh(db)
        print_maslakh_inventory(incidents, plans)
        for i, plan in enumerate(plans, start=1):
            print_cluster(plan, index=i)

        nab = [p for p in plans if p.is_nabatiyeh_example]
        print()
        print("=== Step 5 — Nabatiyeh Al-Maslakh village correctness ===")
        if not nab:
            print("No merge-eligible Al-Maslakh cluster in the current live set.")
        for plan in nab:
            print(
                f"  cluster size={plan.size} canonical={plan.canonical.id} "
                f"currently {plan.canonical.village_name}({plan.canonical.village_id})"
            )
            print(f"  alias consensus: {plan.village_correction_reason}")
            if plan.village_correction_needed:
                print(
                    f"  RECOMMEND --correct-canonical-village so the surviving "
                    f"row is {plan.proposed_village_name}({plan.proposed_village_id}), "
                    f"not {plan.canonical.village_name}({plan.canonical.village_id})."
                )
            else:
                print("  Canonical village already matches live alias resolution.")

        if not args.apply:
            print()
            print("Dry-run only. Re-run with --apply after review to merge.")
            if any(p.village_correction_needed for p in plans):
                print(
                    "Village correction is opt-in: add --correct-canonical-village "
                    "or the surviving row keeps the (possibly wrong) canonical village_id."
                )
            return

        total = 0
        for plan in plans:
            total += apply_cluster(
                db,
                plan,
                correct_village=args.correct_canonical_village,
            )
        print()
        print(
            f"Applied: soft-deleted {total} incidents across {len(plans)} clusters"
            f"{' (with village correction)' if args.correct_canonical_village else ''}."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
