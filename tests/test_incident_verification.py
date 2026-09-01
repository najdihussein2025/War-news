from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm.exc import StaleDataError

from app.news.dtos import IncidentVerificationDTO
from app.news.services import IncidentConflictError, IncidentNotFoundError, IncidentService


class _Repository:
    def __init__(self, result=SimpleNamespace(id="incident"), *, stale=False):
        self.result = result
        self.stale = stale
        self.calls = []

    def set_verification(self, incident_id, status, reason, version, user_id):
        self.calls.append((incident_id, status, reason, version, user_id))
        if self.stale:
            raise StaleDataError()
        return self.result


def test_rejection_requires_a_reason() -> None:
    with pytest.raises(ValidationError, match="rejection reason"):
        IncidentVerificationDTO(status="rejected", version=1)


def test_service_records_human_verification() -> None:
    repository = _Repository()
    incident_id = uuid4()
    user_id = uuid4()
    payload = IncidentVerificationDTO(status="verified", reason="Confirmed by source", version=3)

    result = IncidentService(repository).set_verification(incident_id, payload, user_id)  # type: ignore[arg-type]

    assert result.id == "incident"
    assert repository.calls == [(incident_id, "verified", "Confirmed by source", 3, user_id)]


def test_service_maps_missing_and_stale_reviews() -> None:
    payload = IncidentVerificationDTO(status="verified", version=1)
    with pytest.raises(IncidentNotFoundError):
        IncidentService(_Repository(result=None)).set_verification(uuid4(), payload, uuid4())  # type: ignore[arg-type]
    with pytest.raises(IncidentConflictError):
        IncidentService(_Repository(stale=True)).set_verification(uuid4(), payload, uuid4())  # type: ignore[arg-type]
