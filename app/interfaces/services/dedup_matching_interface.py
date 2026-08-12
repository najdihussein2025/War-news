from abc import ABC, abstractmethod
from datetime import date
from typing import Any

from app.models.news import Incident


class DedupMatchingInterface(ABC):
    @abstractmethod
    def find_best_match(
        self,
        village_id: int,
        condition_id: int,
        event_date: date,
        khabar_embedding: list[float],
    ) -> tuple[Incident | None, float]:
        pass

    @abstractmethod
    def merge_into_incident(
        self,
        existing: Incident,
        new_candidate_data: dict[str, Any],
        raw_message_id: int,
    ) -> None:
        pass
