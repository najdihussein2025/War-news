from uuid import UUID

from app.news.dtos import (
    IncidentDetailDTO,
    IncidentListParams,
    IncidentListResponse,
)
from app.news.interfaces import IncidentRepositoryInterface


class IncidentNotFoundError(Exception):
    pass


class IncidentService:
    def __init__(self, incidents: IncidentRepositoryInterface) -> None:
        self.incidents = incidents

    def list_all(self, params: IncidentListParams) -> IncidentListResponse:
        return self.incidents.list_all(params)

    def get_detail(self, incident_id: UUID) -> IncidentDetailDTO:
        incident = self.incidents.get_by_id(incident_id)
        if incident is None:
            raise IncidentNotFoundError("Incident not found.")
        return incident
