from uuid import uuid4

import pytest
from sqlalchemy.orm.exc import StaleDataError

from app.news.services import IncidentConflictError, IncidentService


class _StaleRepository:
    def acquire_edit_lock(self, incident_id, user_id):
        raise StaleDataError("locked")

    def release_edit_lock(self, incident_id, user_id):
        return False


def test_service_rejects_incident_lock_owned_by_another_admin() -> None:
    service = IncidentService(_StaleRepository())  # type: ignore[arg-type]

    with pytest.raises(IncidentConflictError, match="currently being edited"):
        service.acquire_edit_lock(uuid4(), uuid4())
