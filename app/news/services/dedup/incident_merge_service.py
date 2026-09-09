from __future__ import annotations

from typing import Any

from app.news.interfaces import IncidentRepositoryInterface
from app.news.models import Incident


class IncidentMergeService:
    """The single merge path shared by fast-path duplicate linking and full
    materialization.

    Both routes call :meth:`merge` identically. Field-level merge behaviour
    (max-wins casualty counts, structured ``merged_from`` provenance on
    ``incident_updates``, audit row) lives in :meth:`IncidentRepository.merge_existing`;
    this service is the one place callers reach it, so the two routes cannot diverge.
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

    def canonicalize_existing(
        self,
        *,
        canonical: Incident,
        duplicate: Incident,
        new_candidate_data: dict[str, Any],
        similarity_score: float,
    ) -> None:
        """Merge and retire an already-materialized duplicate incident."""
        if duplicate.id == canonical.id:
            return
        if duplicate.raw_message_id is None or duplicate.village_id is None:
            raise ValueError("A duplicate incident must have a raw message and village.")

        self.merge(
            existing=canonical,
            new_candidate_data=new_candidate_data,
            raw_message_id=duplicate.raw_message_id,
        )
        self.incident_repository.soft_delete_for_village_incident(
            duplicate.raw_message_id,
            duplicate.village_id,
            matched_incident_id=canonical.id,
            similarity_score=similarity_score,
        )
