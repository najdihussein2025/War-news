from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any

from app.news.models import Incident


class DedupMatchingInterface(ABC):
    @abstractmethod
    def find_best_match(
        self,
        village_id: int,
        condition_id: int,
        event_date: date,
        khabar_embedding: list[float],
        exclude_raw_message_id: int | None = None,
    ) -> tuple[Incident | None, float]:
        raise NotImplementedError

    @abstractmethod
    def merge_into_incident(
        self,
        existing: Incident,
        new_candidate_data: dict[str, Any],
        raw_message_id: int,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def record_possible_duplicate(
        self,
        incident: Incident,
        matched_incident: Incident,
        similarity_score: float,
    ) -> None:
        raise NotImplementedError
