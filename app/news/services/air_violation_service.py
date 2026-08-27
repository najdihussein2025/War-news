from uuid import UUID

from app.news.dtos import (
    AirViolationCreateDTO,
    AirViolationDTO,
    AirViolationListParams,
    AirViolationListResponse,
    AirViolationSummaryDTO,
    AirViolationUpdateDTO,
)
from sqlalchemy.orm.exc import StaleDataError
from app.news.interfaces import AirViolationRepositoryInterface


class AirViolationNotFoundError(Exception):
    pass


class AirViolationConflictError(Exception):
    pass


class AirViolationService:
    def __init__(self, air_violations: AirViolationRepositoryInterface) -> None:
        self.air_violations = air_violations

    def list_all(self, params: AirViolationListParams) -> AirViolationListResponse:
        return self.air_violations.list_all(params)

    def get_summary(self, params: AirViolationListParams) -> AirViolationSummaryDTO:
        return self.air_violations.get_summary(params)

    def create(self, payload: AirViolationCreateDTO) -> AirViolationDTO:
        if payload.condition_id not in {35, 36, 38}:
            raise ValueError("Condition must be 35, 36, or 38.")
        return self.air_violations.create(payload)

    def update(self, air_violation_id: int, payload: AirViolationUpdateDTO, user_id: UUID) -> AirViolationDTO:
        if payload.condition_id not in {35, 36, 38}:
            raise ValueError("Condition must be 35, 36, or 38.")
        try:
            result = self.air_violations.update(air_violation_id, payload, user_id)
        except StaleDataError as exc:
            raise AirViolationConflictError(
                "This record was updated by another administrator. Please refresh and apply your changes again."
            ) from exc
        if result is None:
            raise AirViolationNotFoundError("Air violation not found.")
        return result

    def delete(self, air_violation_id: int, version: int, user_id: UUID) -> None:
        try:
            deleted = self.air_violations.delete(air_violation_id, version, user_id)
        except StaleDataError as exc:
            raise AirViolationConflictError(
                "This record was updated by another administrator. Refresh before deleting it."
            ) from exc
        if not deleted:
            raise AirViolationNotFoundError("Air violation not found.")

    def acquire_edit_lock(self, air_violation_id: int, user_id: UUID) -> AirViolationDTO:
        try:
            result = self.air_violations.acquire_edit_lock(air_violation_id, user_id)
        except StaleDataError as exc:
            raise AirViolationConflictError(
                "This record is currently being edited by another administrator."
            ) from exc
        if result is None:
            raise AirViolationNotFoundError("Air violation not found.")
        return result

    def release_edit_lock(self, air_violation_id: int, user_id: UUID) -> None:
        self.air_violations.release_edit_lock(air_violation_id, user_id)

    def get_detail(self, air_violation_id: int) -> AirViolationDTO:
        air_violation = self.air_violations.get_detail(air_violation_id)
        if air_violation is None:
            raise AirViolationNotFoundError("Air violation not found.")
        return air_violation
