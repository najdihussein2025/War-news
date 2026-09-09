from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from app.core.config import settings
from app.news.interfaces import DedupMatchingInterface, IncidentRepositoryInterface
from app.news.models import Incident
from app.news.services.dedup.duplicate_comparison_service import (
    DuplicateComparisonService,
    Verdict,
)
from app.news.services.dedup.incident_merge_service import IncidentMergeService

WEIGHT_ACTION_MATCH = 0.35
WEIGHT_EMBEDDING_SIMILARITY = 0.45
WEIGHT_TIME_CLOSENESS = 0.20

assert (
    WEIGHT_ACTION_MATCH + WEIGHT_EMBEDDING_SIMILARITY + WEIGHT_TIME_CLOSENESS
) == 1.0

DEDUP_HIGH_THRESHOLD: float = settings.dedup_high_threshold
DEDUP_LOW_THRESHOLD: float = settings.dedup_low_threshold

_VERDICT_RANK: dict[Verdict, int] = {
    "distinct": 0,
    "possible_duplicate": 1,
    "high_confidence_duplicate": 2,
}


class DedupMatchingService(DedupMatchingInterface):
    """Embedding-weighted candidate lookup gated by DuplicateComparisonService.

    Used by full materialization and Tier-2 backstop — *not* as an override of
    FastPathDedupService. Candidate rows are pulled inside the fast-path outer
    lookup window; the verdict (including the 6h cutoff) comes from
    DuplicateComparisonService so Mansouri-class multi-day pairs stay distinct.
    """

    def __init__(
        self,
        incident_repository: IncidentRepositoryInterface,
        comparison_service: DuplicateComparisonService | None = None,
    ) -> None:
        self.incident_repository = incident_repository
        self.merge_service = IncidentMergeService(incident_repository)
        self.comparison = comparison_service or DuplicateComparisonService()

    def find_best_match(
        self,
        village_id: int,
        condition_id: int,
        event_date: date,
        khabar_embedding: list[float],
        exclude_raw_message_id: int | None = None,
        event_time: time | None = None,
    ) -> tuple[Incident | None, float]:
        cfg = self.comparison.config
        window_days = cfg.lookup_window_days
        candidates = self.incident_repository.list_duplicate_candidates(
            village_id=village_id,
            event_date=event_date,
            khabar_embedding=khabar_embedding,
            window_days=window_days,
            exclude_raw_message_id=exclude_raw_message_id,
        )
        if not candidates:
            return None, 0.0

        candidate_dt = datetime.combine(event_date, event_time or time(0, 0))
        best: tuple[Incident, float, int] | None = None
        for incident, embedding_similarity in candidates:
            if incident.condition_id != condition_id:
                continue
            incident_dt = datetime.combine(
                incident.event_date, incident.event_time or time(0, 0)
            )
            gap_seconds = abs((incident_dt - candidate_dt).total_seconds())
            result = self.comparison.compare(
                time_gap_seconds=gap_seconds,
                text_similarity=None,
                embedding_similarity=float(embedding_similarity),
            )
            if result.verdict == "distinct":
                continue
            rank = _VERDICT_RANK[result.verdict]
            score = result.similarity_score
            if best is None or rank > best[2] or (
                rank == best[2] and score > best[1]
            ):
                best = (incident, score, rank)

        if best is None:
            return None, 0.0
        return best[0], best[1]

    def merge_into_incident(
        self,
        existing: Incident,
        new_candidate_data: dict[str, Any],
        raw_message_id: int,
    ) -> None:
        self.merge_service.merge(
            existing=existing,
            new_candidate_data=new_candidate_data,
            raw_message_id=raw_message_id,
        )

    def canonicalize_existing_incident(
        self,
        canonical: Incident,
        duplicate: Incident,
        new_candidate_data: dict[str, Any],
        similarity_score: float,
    ) -> None:
        self.merge_service.canonicalize_existing(
            canonical=canonical,
            duplicate=duplicate,
            new_candidate_data=new_candidate_data,
            similarity_score=similarity_score,
        )

    def record_possible_duplicate(
        self,
        incident: Incident,
        matched_incident: Incident,
        similarity_score: float,
    ) -> None:
        self.incident_repository.create_duplicate_match(
            incident=incident,
            matched_incident=matched_incident,
            similarity_score=similarity_score,
        )

    @staticmethod
    def _score_candidate(
        incident: Incident,
        condition_id: int,
        event_date: date,
        embedding_similarity: float,
        window_days: int,
    ) -> float:
        action_score = (
            1.0 if incident.condition_id == condition_id else 0.0
        ) * WEIGHT_ACTION_MATCH
        days_apart = abs((incident.event_date - event_date).days)
        time_closeness = max(
            0.0,
            1.0 - (days_apart / float(window_days)),
        )
        return (
            action_score
            + (embedding_similarity * WEIGHT_EMBEDDING_SIMILARITY)
            + (time_closeness * WEIGHT_TIME_CLOSENESS)
        )
