from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from datetime import date
from typing import Any

from app.llm.dtos import ExtractedCandidate
from app.news.models import (
    Incident,
    RawMessage,
)


class IncidentRepositoryInterface(ABC):
    @abstractmethod
    def list_duplicate_candidates(
        self,
        village_id: int,
        event_date: date,
        khabar_embedding: list[float],
        window_days: int,
    ) -> list[tuple[Incident, float]]:
        pass

    @abstractmethod
    def create_with_detail(
        self,
        message: RawMessage,
        candidate: ExtractedCandidate,
        village_id: int,
        condition_id: int,
        khabar_embedding: list[float],
        duplicate_flag: bool = False,
    ) -> Incident:
        pass

    @abstractmethod
    def create_duplicate_match(
        self,
        incident: Incident,
        matched_incident: Incident,
        similarity_score: float,
    ) -> None:
        pass

    @abstractmethod
    def merge_existing(
        self,
        existing: Incident,
        new_candidate_data: dict[str, Any],
        raw_message_id: int,
    ) -> None:
        pass

    @abstractmethod
    def begin_nested(self) -> AbstractContextManager[object]:
        pass

    @abstractmethod
    def rollback(self) -> None:
        pass
