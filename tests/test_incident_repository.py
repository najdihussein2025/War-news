from uuid import uuid4

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.news.models import Incident
from app.news.repositories.incident_repository import IncidentRepository


class _ScalarResult:
    def __init__(self, incidents: list[Incident]) -> None:
        self.incidents = incidents

    def all(self) -> list[Incident]:
        return self.incidents


class _SessionStub:
    def __init__(self, incidents: list[Incident]) -> None:
        self.incidents = incidents
        self.added: list[Incident] = []
        self.flush_calls = 0

    def scalars(self, _statement) -> _ScalarResult:
        return _ScalarResult(self.incidents)

    def add(self, incident: Incident) -> None:
        self.added.append(incident)

    def flush(self) -> None:
        self.flush_calls += 1


def test_soft_delete_for_raw_message_id_stages_live_incidents() -> None:
    incident = Incident()
    incident.id = uuid4()
    incident.is_deleted = False
    db = _SessionStub([incident])

    deleted_ids = IncidentRepository(db).soft_delete_for_raw_message_id(42)  # type: ignore[arg-type]

    assert deleted_ids == [incident.id]
    assert incident.is_deleted is True
    assert db.added == [incident]
    assert db.flush_calls == 1


def test_soft_delete_for_raw_message_id_is_idempotent() -> None:
    db = _SessionStub([])

    deleted_ids = IncidentRepository(db).soft_delete_for_raw_message_id(42)  # type: ignore[arg-type]

    assert deleted_ids == []
    assert db.added == []
    assert db.flush_calls == 1
