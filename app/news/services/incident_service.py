from uuid import UUID

from app.news.dtos import (
    IncidentDetailDTO,
    IncidentCreateDTO,
    IncidentListParams,
    IncidentListResponse,
    IncidentUpdateDTO,
)
from app.news.interfaces import IncidentRepositoryInterface


class IncidentNotFoundError(Exception):
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

    def update(self, incident_id: UUID, payload: IncidentUpdateDTO) -> IncidentDetailDTO:
        incident = self.incidents.update(incident_id, payload)
        if incident is None:
            raise IncidentNotFoundError("Incident not found.")
        return incident

    def delete(self, incident_id: UUID) -> None:
        if not self.incidents.delete(incident_id):
            raise IncidentNotFoundError("Incident not found.")
