from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from app.news.repositories.incident_repository import IncidentRepository
from app.news.services.dedup.duplicate_comparison_service import DuplicateComparisonService

if TYPE_CHECKING:
    from app.news.models import Incident


class FastPathDedupOutcome(str, Enum):
    confident_duplicate = "confident_duplicate"
    possible_duplicate = "possible_duplicate"
    materialize = "materialize"
    skip_ineligible = "skip_ineligible"


@dataclass(frozen=True)
class FastPathDedupDecision:
    outcome: FastPathDedupOutcome
    canonical_incident_id: UUID | None = None
    representative_raw_message_id: int | None = None
    canonical_incident: Incident | None = None
    # Populated for possible_duplicate: the active incident the new row should be
    # flagged against for human review.
    matched_incident: Incident | None = None
    similarity_score: float | None = None
    similarity_method: str | None = None


CONFIDENT_MATCH_STATUSES = frozenset({"matched"})
MATERIALIZE_MATCH_STATUSES = frozenset({"matched", "matched_low_confidence"})


class FastPathDedupService:
    def __init__(
        self,
        incident_repository: IncidentRepository,
        comparison_service: DuplicateComparisonService | None = None,
    ) -> None:
        self.incidents = incident_repository
        self.comparison = comparison_service or DuplicateComparisonService()

    def decide_for_village(
        self,
        *,
        village_match_status: str | None,
        condition_match_status: str | None,
        village_id: int | None,
        condition_id: int | None,
        message_datetime: datetime,
        candidate_text: str | None = None,
        candidate_embedding: list[float] | None = None,
        exclude_raw_message_id: int | None = None,
    ) -> FastPathDedupDecision:
        if village_id is None or condition_id is None:
            return FastPathDedupDecision(outcome=FastPathDedupOutcome.skip_ineligible)

        if village_match_status not in MATERIALIZE_MATCH_STATUSES:
            return FastPathDedupDecision(outcome=FastPathDedupOutcome.skip_ineligible)
        if condition_match_status not in MATERIALIZE_MATCH_STATUSES:
            return FastPathDedupDecision(outcome=FastPathDedupOutcome.skip_ineligible)

        # Same village_id + same condition_id at *confident* status remains the
        # primary path (may auto-merge on high_confidence).
        if (
            village_match_status in CONFIDENT_MATCH_STATUSES
            and condition_match_status in CONFIDENT_MATCH_STATUSES
        ):
            same_village = self._decide_same_village(
                village_id=village_id,
                condition_id=condition_id,
                message_datetime=message_datetime,
                candidate_text=candidate_text,
                candidate_embedding=candidate_embedding,
                exclude_raw_message_id=exclude_raw_message_id,
            )
            if same_village.outcome != FastPathDedupOutcome.materialize:
                return same_village

        # Cross-village backstop: elevated text similarity within ≤30min flags
        # possible_duplicate for human review only — never auto-merges.
        return self._decide_cross_village(
            village_id=village_id,
            condition_id=condition_id,
            message_datetime=message_datetime,
            candidate_text=candidate_text,
            candidate_embedding=candidate_embedding,
            exclude_raw_message_id=exclude_raw_message_id,
        )

    def _decide_same_village(
        self,
        *,
        village_id: int,
        condition_id: int,
        message_datetime: datetime,
        candidate_text: str | None,
        candidate_embedding: list[float] | None,
        exclude_raw_message_id: int | None,
    ) -> FastPathDedupDecision:
        candidates = self.incidents.find_fast_dedup_candidates(
            village_id=village_id,
            condition_id=condition_id,
            message_datetime=message_datetime,
            lookup_window_days=self.comparison.config.lookup_window_days,
            candidate_text=candidate_text,
            candidate_embedding=candidate_embedding,
            exclude_raw_message_id=exclude_raw_message_id,
        )
        if not candidates:
            return FastPathDedupDecision(outcome=FastPathDedupOutcome.materialize)

        first_possible: FastPathDedupDecision | None = None
        for candidate in candidates:  # already sorted by time gap ascending
            result = self.comparison.compare(
                time_gap_seconds=candidate.time_gap_seconds,
                text_similarity=candidate.text_similarity,
                embedding_similarity=candidate.embedding_similarity,
            )
            if result.verdict == "high_confidence_duplicate":
                return FastPathDedupDecision(
                    outcome=FastPathDedupOutcome.confident_duplicate,
                    canonical_incident_id=candidate.incident.id,
                    representative_raw_message_id=candidate.incident.raw_message_id,
                    canonical_incident=candidate.incident,
                    matched_incident=candidate.incident,
                    similarity_score=result.similarity_score,
                    similarity_method=result.similarity_method,
                )
            if result.verdict == "possible_duplicate" and first_possible is None:
                first_possible = FastPathDedupDecision(
                    outcome=FastPathDedupOutcome.possible_duplicate,
                    canonical_incident_id=candidate.incident.id,
                    representative_raw_message_id=candidate.incident.raw_message_id,
                    canonical_incident=candidate.incident,
                    matched_incident=candidate.incident,
                    similarity_score=result.similarity_score,
                    similarity_method=result.similarity_method,
                )

        if first_possible is not None:
            return first_possible

        return FastPathDedupDecision(outcome=FastPathDedupOutcome.materialize)

    def _decide_cross_village(
        self,
        *,
        village_id: int,
        condition_id: int,
        message_datetime: datetime,
        candidate_text: str | None,
        candidate_embedding: list[float] | None,
        exclude_raw_message_id: int | None,
    ) -> FastPathDedupDecision:
        find_cross = getattr(
            self.incidents, "find_cross_village_dedup_candidates", None
        )
        if find_cross is None:
            return FastPathDedupDecision(outcome=FastPathDedupOutcome.materialize)

        candidates = find_cross(
            village_id=village_id,
            condition_id=condition_id,
            message_datetime=message_datetime,
            lookup_window_days=self.comparison.config.lookup_window_days,
            min_text_similarity=self.comparison.config.cross_village_text_min,
            candidate_text=candidate_text,
            candidate_embedding=candidate_embedding,
            exclude_raw_message_id=exclude_raw_message_id,
        )
        for candidate in candidates:
            result = self.comparison.compare(
                time_gap_seconds=candidate.time_gap_seconds,
                text_similarity=candidate.text_similarity,
                embedding_similarity=candidate.embedding_similarity,
                village_match_uncertain=True,
            )
            # Hard rule: cross-village never auto-merges.
            if result.verdict == "possible_duplicate":
                return FastPathDedupDecision(
                    outcome=FastPathDedupOutcome.possible_duplicate,
                    canonical_incident_id=candidate.incident.id,
                    representative_raw_message_id=candidate.incident.raw_message_id,
                    canonical_incident=candidate.incident,
                    matched_incident=candidate.incident,
                    similarity_score=result.similarity_score,
                    similarity_method=result.similarity_method,
                )
        return FastPathDedupDecision(outcome=FastPathDedupOutcome.materialize)
