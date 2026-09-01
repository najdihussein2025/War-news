from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from datetime import date
from typing import Any
from uuid import UUID

from app.llm.dtos import ExtractedCandidate
from app.news.dtos import (
    IncidentDetailDTO,
    IncidentDuplicateCandidateDTO,
    IncidentDuplicateResolutionResultDTO,
    IncidentCreateDTO,
    IncidentListParams,
    IncidentListResponse,
    IncidentUpdateDTO,
)
from app.news.models import (
    Incident,
    RawMessage,
)


class IncidentRepositoryInterface(ABC):
    @abstractmethod
    def list_all(self, params: IncidentListParams) -> IncidentListResponse:
        pass

    @abstractmethod
    def get_by_id(self, incident_id: UUID) -> IncidentDetailDTO | None:
        pass

    @abstractmethod
    def create_manual(self, payload: IncidentCreateDTO, created_by: UUID) -> IncidentDetailDTO:
        pass

    @abstractmethod
    def update(self, incident_id: UUID, payload: IncidentUpdateDTO, user_id: UUID) -> IncidentDetailDTO | None:
        pass

    @abstractmethod
    def update_details(self, incident_id: UUID, fields: dict[str, Any], performed_by: UUID, version: int) -> IncidentDetailDTO | None:
        pass

    @abstractmethod
    def delete(self, incident_id: UUID, version: int, user_id: UUID) -> bool:
        pass

    @abstractmethod
    def acquire_edit_lock(self, incident_id: UUID, user_id: UUID) -> IncidentDetailDTO | None:
        pass

    @abstractmethod
    def release_edit_lock(self, incident_id: UUID, user_id: UUID) -> bool:
        pass

    @abstractmethod
    def get_pending_duplicate_candidate(
        self, incident_id: UUID
    ) -> IncidentDuplicateCandidateDTO | None:
        pass

    @abstractmethod
    def resolve_duplicate(
        self,
        incident_id: UUID,
        match_id: int,
        decision: str,
        version: int,
        user_id: UUID,
    ) -> IncidentDuplicateResolutionResultDTO | None:
        pass

    @abstractmethod
    def list_duplicate_candidates(
        self,
        village_id: int,
        event_date: date,
        khabar_embedding: list[float],
        window_days: int,
        exclude_raw_message_id: int | None = None,
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
    def soft_delete_for_raw_message_id(self, raw_message_id: int) -> list[UUID]:
        pass

    @abstractmethod
    def begin_nested(self) -> AbstractContextManager[object]:
        pass

    @abstractmethod
    def rollback(self) -> None:
        pass
