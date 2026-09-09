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
        note="human note",
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
    assert existing.note == "human note"
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
    assert update.new_values["merged_from"] == {
        "raw_message_id": 42,
        "channel": "CNRS Webhook",
        "khabar": "follow-up",
    }


def test_merge_does_not_append_khabar_into_note() -> None:
    existing = Incident(id=uuid4(), note=None, duplicate_flag=True)
    raw_message = SimpleNamespace(
        source_name="Telegram",
        origin_account=None,
        source_platform=None,
    )
    db = _MergeSessionStub(raw_message=raw_message)
    repo = IncidentRepository(db)  # type: ignore[arg-type]

    repo.merge_existing(
        existing,
        {"khabar": "Automated should not land in note"},
        raw_message_id=99,
    )

    assert existing.note is None
    update = next(item for item in db.added if isinstance(item, IncidentUpdate))
    assert "Automated duplicate merge" not in str(update.new_values.get("note"))
    assert update.new_values["merged_from"] == {
        "raw_message_id": 99,
        "channel": "Telegram",
        "khabar": "Automated should not land in note",
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
    existing = Incident(
        id=uuid4(),
        duplicate_flag=True,
        verification_status="needs_verification",
        verification_reason="Possible duplicate",
    )
    db = _MergeSessionStub(raw_message=None)

    IncidentRepository(db).merge_existing(  # type: ignore[arg-type]
        existing,
        {"khabar": "same event follow-up"},
        raw_message_id=7,
    )

    assert existing.duplicate_flag is False
    assert existing.verification_status == "auto_processed"
    assert existing.verification_reason is None


class _ResolveDuplicateSessionStub:
    def __init__(
        self,
        *,
        duplicate: Incident,
        canonical: Incident,
        match: object,
    ) -> None:
        self.duplicate = duplicate
        self.canonical = canonical
        self.match = match
        self.added: list[object] = []
        self._scalar_calls = 0

    def scalar(self, statement):
        self._scalar_calls += 1
        # First: locked duplicate incident. Second: pending match.
        # Third: canonical. Later: detail lookups return None.
        if self._scalar_calls == 1:
            return self.duplicate
        if self._scalar_calls == 2:
            return self.match
        if self._scalar_calls == 3:
            return self.canonical
        return None

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def test_false_positive_resolution_clears_duplicate_verification() -> None:
    from app.news.models import MatchStatus

    user_id = uuid4()
    duplicate_id = uuid4()
    duplicate = Incident(
        id=duplicate_id,
        version=1,
        locked_by_user_id=user_id,
        duplicate_flag=True,
        verification_status="needs_verification",
        verification_reason="Possible duplicate",
    )
    match = SimpleNamespace(
        id=9,
        matched_incident_id=uuid4(),
        status=MatchStatus.pending,
        resolved_by=None,
    )
    db = _ResolveDuplicateSessionStub(
        duplicate=duplicate,
        canonical=Incident(id=uuid4()),
        match=match,
    )

    IncidentRepository(db).resolve_duplicate(  # type: ignore[arg-type]
        incident_id=duplicate_id,
        match_id=9,
        decision=MatchStatus.false_positive.value,
        version=1,
        user_id=user_id,
    )

    assert duplicate.duplicate_flag is False
    assert duplicate.verification_status == "auto_processed"
    assert duplicate.verification_reason is None
    assert match.status == MatchStatus.false_positive


def test_confirmed_duplicate_resolution_keeps_note_clean_and_records_merged_from() -> None:
    from app.news.models import MatchStatus

    user_id = uuid4()
    duplicate_id = uuid4()
    canonical_id = uuid4()
    duplicate = Incident(
        id=duplicate_id,
        version=1,
        locked_by_user_id=user_id,
        raw_message_id=55,
        khabar="duplicate khabar text",
        note=None,
        deaths=1,
    )
    canonical = Incident(
        id=canonical_id,
        note="keep me",
        deaths=2,
    )
    match = SimpleNamespace(
        id=9,
        matched_incident_id=canonical_id,
        status=MatchStatus.pending,
        resolved_by=None,
    )
    db = _ResolveDuplicateSessionStub(
        duplicate=duplicate,
        canonical=canonical,
        match=match,
    )

    IncidentRepository(db).resolve_duplicate(  # type: ignore[arg-type]
        incident_id=duplicate_id,
        match_id=9,
        decision=MatchStatus.confirmed_duplicate.value,
        version=1,
        user_id=user_id,
    )

    assert canonical.note == "keep me"
    assert "Confirmed duplicate" not in (canonical.note or "")
    merge_updates = [
        item
        for item in db.added
        if isinstance(item, IncidentUpdate) and item.action == UpdateAction.pipeline_merge
    ]
    assert len(merge_updates) == 1
    assert merge_updates[0].new_values["merged_from"] == {
        "raw_message_id": 55,
        "channel": None,
        "khabar": "duplicate khabar text",
    }
