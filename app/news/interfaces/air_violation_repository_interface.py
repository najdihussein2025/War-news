from abc import ABC, abstractmethod

from app.news.dtos import (
    AirViolationDTO,
    AirViolationListParams,
    AirViolationListResponse,
)
from app.news.dtos import MatchResultDTO
from app.news.models import RawMessage


class AirViolationRepositoryInterface(ABC):
    @abstractmethod
    def list_all(self, params: AirViolationListParams) -> AirViolationListResponse:
        pass

    @abstractmethod
    def get_detail(self, air_violation_id: int) -> AirViolationDTO | None:
        pass

    @abstractmethod
    def route_from_match(self, message: RawMessage, result: MatchResultDTO) -> None:
        pass
