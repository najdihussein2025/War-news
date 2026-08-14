from app.news.dtos import (
    AirViolationDTO,
    AirViolationListParams,
    AirViolationListResponse,
)
from app.news.interfaces import AirViolationRepositoryInterface


class AirViolationNotFoundError(Exception):
    pass


class AirViolationService:
    def __init__(self, air_violations: AirViolationRepositoryInterface) -> None:
        self.air_violations = air_violations

    def list_all(self, params: AirViolationListParams) -> AirViolationListResponse:
        return self.air_violations.list_all(params)

    def get_detail(self, air_violation_id: int) -> AirViolationDTO:
        air_violation = self.air_violations.get_detail(air_violation_id)
        if air_violation is None:
            raise AirViolationNotFoundError("Air violation not found.")
        return air_violation
