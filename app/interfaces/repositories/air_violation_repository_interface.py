from abc import ABC, abstractmethod

from app.dtos.news import (
    AirViolationDTO,
    AirViolationListParams,
    AirViolationListResponse,
)


class AirViolationRepositoryInterface(ABC):
    @abstractmethod
    def list_all(self, params: AirViolationListParams) -> AirViolationListResponse:
        pass

    @abstractmethod
    def get_detail(self, air_violation_id: int) -> AirViolationDTO | None:
        pass
