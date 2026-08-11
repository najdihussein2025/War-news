from datetime import date
from typing import Any

from app.interfaces.news import DedupMatchingInterface, IncidentRepositoryInterface
from app.models.news import Incident

# First estimate; tune after reviewing real duplicate decisions.
DEDUP_TIME_WINDOW_DAYS = 3
# First estimate; scores at or above this are merged into the existing incident.
DEDUP_HIGH_THRESHOLD = 0.80
# First estimate; scores at or below this create an unflagged new incident.
DEDUP_LOW_THRESHOLD = 0.50
# First estimate; action agreement weight in the total duplicate score.
WEIGHT_ACTION_MATCH = 0.35
# First estimate; semantic text similarity weight in the total duplicate score.
WEIGHT_EMBEDDING_SIMILARITY = 0.45
# First estimate; event-date closeness weight in the total duplicate score.
WEIGHT_TIME_CLOSENESS = 0.20

assert (
    WEIGHT_ACTION_MATCH + WEIGHT_EMBEDDING_SIMILARITY + WEIGHT_TIME_CLOSENESS
) == 1.0


class DedupMatchingService(DedupMatchingInterface):
    def __init__(self, incident_repository: IncidentRepositoryInterface) -> None:
        self.incident_repository = incident_repository

    def find_best_match(
        self,
        village_id: int,
        condition_id: int,
        event_date: date,
        khabar_embedding: list[float],
    ) -> tuple[Incident | None, float]:
        candidates = self.incident_repository.list_duplicate_candidates(
            village_id=village_id,
            event_date=event_date,
            khabar_embedding=khabar_embedding,
            window_days=DEDUP_TIME_WINDOW_DAYS,
        )
        if not candidates:
            return None, 0.0

        scored_candidates = [
            (
                incident,
                self._score_candidate(
                    incident=incident,
                    condition_id=condition_id,
                    event_date=event_date,
                    embedding_similarity=embedding_similarity,
                ),
            )
            for incident, embedding_similarity in candidates
        ]
        return max(scored_candidates, key=lambda item: item[1])

    def merge_into_incident(
        self,
        existing: Incident,
        new_candidate_data: dict[str, Any],
        raw_message_id: int,
    ) -> None:
        self.incident_repository.merge_existing(
            existing=existing,
            new_candidate_data=new_candidate_data,
            raw_message_id=raw_message_id,
        )

    @staticmethod
    def _score_candidate(
        incident: Incident,
        condition_id: int,
        event_date: date,
        embedding_similarity: float,
    ) -> float:
        action_score = (
            1.0 if incident.condition_id == condition_id else 0.0
        ) * WEIGHT_ACTION_MATCH
        days_apart = abs((incident.event_date - event_date).days)
        time_closeness = max(
            0.0,
            1.0 - (days_apart / float(DEDUP_TIME_WINDOW_DAYS)),
        )
        return (
            action_score
            + (embedding_similarity * WEIGHT_EMBEDDING_SIMILARITY)
            + (time_closeness * WEIGHT_TIME_CLOSENESS)
        )
