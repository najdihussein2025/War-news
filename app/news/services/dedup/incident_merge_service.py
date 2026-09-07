from __future__ import annotations

from typing import Any

from app.news.interfaces import IncidentRepositoryInterface
from app.news.models import Incident


class IncidentMergeService:
    """The single merge path shared by fast-path duplicate linking and full
    materialization.

    Both routes call :meth:`merge` identically. Field-level merge behaviour
    (max-wins casualty counts, note provenance, ``incident_updates`` audit
    row) lives in :meth:`IncidentRepository.merge_existing`; this service is
    the one place callers reach it, so the two routes cannot diverge.
    """

    def __init__(self, incident_repository: IncidentRepositoryInterface) -> None:
        self.incident_repository = incident_repository

    def merge(
        self,
        *,
        existing: Incident,
        new_candidate_data: dict[str, Any],
        raw_message_id: int,
    ) -> None:
        self.incident_repository.merge_existing(
            existing=existing,
            new_candidate_data=new_candidate_data,
            raw_message_id=raw_message_id,
        )
