from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy.orm.exc import StaleDataError

from app.news.dtos import (
    DuplicateCandidateIncidentDTO,
    IncidentDuplicateCandidateDTO,
    IncidentDuplicateResolutionDTO,
    IncidentDuplicateResolutionResultDTO,
)
from app.news.services import IncidentConflictError, IncidentNotFoundError, IncidentService


class _DuplicateReviewRepository:
    def __init__(self) -> None:
        self.candidate = None
        self.result = None
        self.resolve_args = None
        self.stale = False

    def get_pending_duplicate_candidate(self, incident_id):
        return self.candidate

    def resolve_duplicate(self, incident_id, match_id, decision, version, user_id):
        if self.stale:
            raise StaleDataError("stale")
        self.resolve_args = (incident_id, match_id, decision, version, user_id)
        return self.result


def test_service_returns_pending_duplicate_candidate() -> None:
    incident_id = uuid4()
    candidate_id = uuid4()
    repository = _DuplicateReviewRepository()
    repository.candidate = IncidentDuplicateCandidateDTO(
        match_id=7,
        similarity_score=0.65,
        candidate=DuplicateCandidateIncidentDTO(
            id=candidate_id,
            village="Tyre",
            condition="Airstrike",
            event_date=date(2026, 8, 31),
            event_time=None,
            khabar="Existing report",
            source="Telegram",
            source_reference="channel-a",
            total_deaths=None,
            total_injuries=2,
        ),
    )

    result = IncidentService(repository).get_duplicate_candidate(incident_id)  # type: ignore[arg-type]

    assert result.match_id == 7
    assert result.similarity_score == 0.65
    assert result.candidate.id == candidate_id


def test_service_rejects_missing_duplicate_candidate() -> None:
    with pytest.raises(IncidentNotFoundError, match="candidate not found"):
        IncidentService(_DuplicateReviewRepository()).get_duplicate_candidate(uuid4())  # type: ignore[arg-type]


def test_service_delegates_false_positive_resolution() -> None:
    incident_id = uuid4()
    user_id = uuid4()
    repository = _DuplicateReviewRepository()
    repository.result = IncidentDuplicateResolutionResultDTO(
        decision="false_positive",
        incident_id=incident_id,
        canonical_incident_id=incident_id,
    )
    payload = IncidentDuplicateResolutionDTO(
        match_id=9,
        decision="false_positive",
        version=4,
    )

    result = IncidentService(repository).resolve_duplicate(incident_id, payload, user_id)  # type: ignore[arg-type]

    assert result.decision == "false_positive"
    assert repository.resolve_args == (incident_id, 9, "false_positive", 4, user_id)


def test_service_maps_stale_duplicate_resolution_to_conflict() -> None:
    repository = _DuplicateReviewRepository()
    repository.stale = True
    payload = IncidentDuplicateResolutionDTO(
        match_id=9,
        decision="confirmed_duplicate",
        version=4,
    )

    with pytest.raises(IncidentConflictError, match="duplicate review"):
        IncidentService(repository).resolve_duplicate(uuid4(), payload, uuid4())  # type: ignore[arg-type]
