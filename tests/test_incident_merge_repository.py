from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.news.models import Incident, IncidentDetail, IncidentUpdate, UpdateAction
from app.news.repositories.incident_repository import IncidentRepository


class _MergeSessionStub:
    def __init__(
        self,
        *,
        raw_message: object | None,
        detail: IncidentDetail | None = None,
    ) -> None:
        self.raw_message = raw_message
        self.detail = detail
        self.added: list[object] = []

    def get(self, model, pk):
        if model.__name__ == "RawMessage":
            return self.raw_message
        return None

    def scalar(self, _statement):
        return self.detail

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        return None


def test_merge_keeps_higher_count_and_records_suppressed_incoming() -> None:
    incident_id = uuid4()
    existing = Incident(
        id=incident_id,
        deaths=10,
        injuries=4,
        total_deaths=10,
        total_injuries=4,
        details_pending=False,
    )
    raw_message = SimpleNamespace(
        source_name="CNRS Webhook",
        origin_account=None,
        source_platform=None,
    )
    db = _MergeSessionStub(raw_message=raw_message)
    repo = IncidentRepository(db)  # type: ignore[arg-type]

    repo.merge_existing(
        existing,
        {
            "deaths": 3,
            "injuries": 8,
            "total_deaths": 3,
            "total_injuries": 8,
            "khabar": "follow-up",
        },
        raw_message_id=42,
    )

    assert existing.deaths == 10
    assert existing.injuries == 8
    update = next(item for item in db.added if isinstance(item, IncidentUpdate))
    assert update.action == UpdateAction.pipeline_merge
    assert update.new_values["deaths"] == 10
    assert update.new_values["deaths_suppressed"] == {
        "value": 3,
        "raw_message_id": 42,
        "channel": "CNRS Webhook",
    }
    assert update.new_values["total_deaths_suppressed"] == {
        "value": 3,
        "raw_message_id": 42,
        "channel": "CNRS Webhook",
    }


def test_merge_reopens_details_pending_for_new_presence_category() -> None:
    incident_id = uuid4()
    existing = Incident(id=incident_id, details_pending=False)
    detail = IncidentDetail(incident_id=incident_id, la=None)
    db = _MergeSessionStub(raw_message=None, detail=detail)
    repo = IncidentRepository(db)  # type: ignore[arg-type]

    repo.merge_existing(
        existing,
        {"mapped_fields": {"la": True, "la_did": "D"}},
        raw_message_id=7,
    )

    assert existing.details_pending is True
    assert detail.la is True


def test_merge_does_not_reopen_details_pending_for_existing_category() -> None:
    incident_id = uuid4()
    existing = Incident(id=incident_id, details_pending=False)
    detail = IncidentDetail(incident_id=incident_id, la=True, la_did="D")
    db = _MergeSessionStub(raw_message=None, detail=detail)
    repo = IncidentRepository(db)  # type: ignore[arg-type]

    repo.merge_existing(
        existing,
        {"mapped_fields": {"la": True, "la_did": "D"}},
        raw_message_id=7,
    )

    assert existing.details_pending is False


def test_merge_clears_stale_duplicate_flag_without_transition_conflict() -> None:
    existing = Incident(id=uuid4(), duplicate_flag=True)
    db = _MergeSessionStub(raw_message=None)

    IncidentRepository(db).merge_existing(  # type: ignore[arg-type]
        existing,
        {"khabar": "same event follow-up"},
        raw_message_id=7,
    )

    assert existing.duplicate_flag is False
