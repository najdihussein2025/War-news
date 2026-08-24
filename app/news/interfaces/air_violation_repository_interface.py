from abc import ABC, abstractmethod

from app.news.dtos import (
    AirViolationCreateDTO,
    AirViolationDTO,
    AirViolationListParams,
    AirViolationListResponse,
)
from app.news.dtos import MatchResultDTO
from app.news.models import RawMessage


class AirViolationRepositoryInterface(ABC):
    @abstractmethod
    def create(self, payload: AirViolationCreateDTO) -> AirViolationDTO:
        pass

    @abstractmethod
    def update(self, air_violation_id: int, payload: AirViolationCreateDTO) -> AirViolationDTO | None:
        pass

    @abstractmethod
    def delete(self, air_violation_id: int) -> bool:
        pass

    @abstractmethod
    def list_all(self, params: AirViolationListParams) -> AirViolationListResponse:
        pass

    @abstractmethod
    def get_detail(self, air_violation_id: int) -> AirViolationDTO | None:
        pass

    @abstractmethod
    def route_from_match(self, message: RawMessage, result: MatchResultDTO) -> bool:
        pass

    @abstractmethod
    def discard_for_message(self, message: RawMessage) -> None:
        pass
