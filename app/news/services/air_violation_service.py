from app.news.dtos import (
    AirViolationCreateDTO,
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

    def create(self, payload: AirViolationCreateDTO) -> AirViolationDTO:
        if payload.condition_id not in {35, 36, 38}:
            raise ValueError("Condition must be 35, 36, or 38.")
        return self.air_violations.create(payload)

    def update(self, air_violation_id: int, payload: AirViolationCreateDTO) -> AirViolationDTO:
        if payload.condition_id not in {35, 36, 38}:
            raise ValueError("Condition must be 35, 36, or 38.")
        result = self.air_violations.update(air_violation_id, payload)
        if result is None:
            raise AirViolationNotFoundError("Air violation not found.")
        return result

    def delete(self, air_violation_id: int) -> None:
        if not self.air_violations.delete(air_violation_id):
            raise AirViolationNotFoundError("Air violation not found.")

    def get_detail(self, air_violation_id: int) -> AirViolationDTO:
        air_violation = self.air_violations.get_detail(air_violation_id)
        if air_violation is None:
            raise AirViolationNotFoundError("Air violation not found.")
        return air_violation
