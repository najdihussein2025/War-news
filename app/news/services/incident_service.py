from uuid import UUID
from sqlalchemy.orm.exc import StaleDataError

from app.news.dtos import (
    IncidentDetailDTO,
    IncidentCreateDTO,
    IncidentDetailsPatchDTO,
    IncidentListParams,
    IncidentListResponse,
    IncidentUpdateDTO,
)
from app.news.interfaces import IncidentRepositoryInterface


class IncidentNotFoundError(Exception):
    pass


class IncidentConflictError(Exception):
    pass


class IncidentService:
    def __init__(self, incidents: IncidentRepositoryInterface) -> None:
        self.incidents = incidents

    def list_all(self, params: IncidentListParams) -> IncidentListResponse:
        return self.incidents.list_all(params)

    def create(self, payload: IncidentCreateDTO, created_by: UUID) -> IncidentDetailDTO:
        return self.incidents.create_manual(payload, created_by)

    def get_detail(self, incident_id: UUID) -> IncidentDetailDTO:
        incident = self.incidents.get_by_id(incident_id)
        if incident is None:
            raise IncidentNotFoundError("Incident not found.")
        return incident

    def update(self, incident_id: UUID, payload: IncidentUpdateDTO, user_id: UUID) -> IncidentDetailDTO:
        try:
            incident = self.incidents.update(incident_id, payload, user_id)
        except StaleDataError as exc:
            raise IncidentConflictError("This incident was changed or locked by another administrator.") from exc
        if incident is None:
            raise IncidentNotFoundError("Incident not found.")
        return incident

    def update_details(
        self,
        incident_id: UUID,
        payload: IncidentDetailsPatchDTO,
        performed_by: UUID,
    ) -> IncidentDetailDTO:
        try:
            incident = self.incidents.update_details(
                incident_id,
                payload.fields,
                performed_by,
                payload.version,
            )
        except StaleDataError as exc:
            raise IncidentConflictError(
                "This incident was changed or locked by another administrator."
            ) from exc
        if incident is None:
            raise IncidentNotFoundError("Incident not found.")
        return incident

    def delete(self, incident_id: UUID, version: int, user_id: UUID) -> None:
        try:
            deleted = self.incidents.delete(incident_id, version, user_id)
        except StaleDataError as exc:
            raise IncidentConflictError("This incident was changed or locked by another administrator.") from exc
        if not deleted:
            raise IncidentNotFoundError("Incident not found.")

    def acquire_edit_lock(self, incident_id: UUID, user_id: UUID) -> IncidentDetailDTO:
        try:
            incident = self.incidents.acquire_edit_lock(incident_id, user_id)
        except StaleDataError as exc:
            raise IncidentConflictError("This incident is currently being edited by another administrator.") from exc
        if incident is None:
            raise IncidentNotFoundError("Incident not found.")
        return incident

    def release_edit_lock(self, incident_id: UUID, user_id: UUID) -> None:
        self.incidents.release_edit_lock(incident_id, user_id)
