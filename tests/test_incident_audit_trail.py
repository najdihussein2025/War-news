from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.news.dtos.incident_dto import IncidentCreateDTO, IncidentUpdateDTO
from app.news.models import DeletedReason, IncidentUpdate, UpdateAction
from app.news.repositories.incident_repository import IncidentRepository


def _added_updates(db: MagicMock) -> list[IncidentUpdate]:
    return [
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], IncidentUpdate)
    ]


def _incident(**overrides):
    base = dict(
        id=uuid4(),
        raw_message_id=None,
        version=3,
        event_date=date(2026, 9, 20),
        event_time=None,
        event_month="September",
        khabar="old report",
        note=None,
        worker_name=None,
        source_link="https://a.example/1",
        source_link_2="https://b.example/2",
        total_deaths=1,
        total_injuries=None,
        deaths=1,
        injuries=None,
        is_deleted=False,
        deleted_reason=None,
        duplicate_flag=False,
        locked_by_user_id=None,
        edit_lock_expires_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _repo(db: MagicMock) -> IncidentRepository:
    repo = IncidentRepository(db)
    repo.get_by_id = MagicMock(return_value="detail")
    return repo


def test_put_without_source_link_2_keeps_it_and_logs_an_edit() -> None:
    db = MagicMock()
    user_id = uuid4()
    incident = _incident(locked_by_user_id=user_id)
    db.scalar.return_value = incident
    payload = IncidentUpdateDTO(
        version=3,
        event_date=date(2026, 9, 20),
        khabar="new report",
        source_link="https://a.example/1",
        total_deaths=2,
        deaths=2,
    )

    _repo(db).update(incident.id, payload, user_id)

    assert incident.source_link_2 == "https://b.example/2"
    assert incident.khabar == "new report"
    [entry] = _added_updates(db)
    assert entry.action == UpdateAction.edit
    assert entry.performed_by == user_id
    assert entry.old_values == {"khabar": "old report", "total_deaths": 1, "deaths": 1}
    assert entry.new_values == {"khabar": "new report", "total_deaths": 2, "deaths": 2}


def test_put_with_no_real_change_writes_no_audit_row() -> None:
    db = MagicMock()
    user_id = uuid4()
    incident = _incident(locked_by_user_id=user_id)
    db.scalar.return_value = incident
    payload = IncidentUpdateDTO(version=3, event_date=date(2026, 9, 20), khabar="old report")

    _repo(db).update(incident.id, payload, user_id)

    assert _added_updates(db) == []


def test_admin_delete_logs_and_marks_admin_reason() -> None:
    db = MagicMock()
    user_id = uuid4()
    incident = _incident(locked_by_user_id=user_id)
    db.scalar.return_value = incident

    assert _repo(db).delete(incident.id, 3, user_id) is True

    assert incident.is_deleted is True
    assert incident.deleted_reason == DeletedReason.admin.value
    [entry] = _added_updates(db)
    assert entry.action == UpdateAction.delete
    assert entry.performed_by == user_id
    assert entry.new_values["deleted_reason"] == "admin"


def test_manual_create_logs_a_create_row() -> None:
    db = MagicMock()
    user_id = uuid4()
    village = SimpleNamespace(id=11)
    condition = SimpleNamespace(id=22)
    db.scalar.side_effect = [village, condition]
    repo = _repo(db)
    repo._ensure_manual_source = MagicMock(return_value=SimpleNamespace(id=5))

    repo.create_manual(
        IncidentCreateDTO(
            village="Kfarkela",
            condition="Shelling",
            event_date=date(2026, 9, 24),
            khabar="report",
        ),
        user_id,
    )

    [entry] = _added_updates(db)
    assert entry.action == UpdateAction.create
    assert entry.performed_by == user_id
    assert entry.new_values["village_id"] == 11
    assert entry.new_values["event_date"] == "2026-09-24"


def test_pipeline_soft_delete_logs_reason_and_canonical() -> None:
    db = MagicMock()
    retired = _incident()
    canonical = _incident()
    db.scalars.return_value.all.return_value = [retired]
    db.get.return_value = canonical
    repo = _repo(db)
    repo.redirect_pending_duplicate_matches = MagicMock()
    repo.create_duplicate_match = MagicMock()

    repo.soft_delete_for_village_incident(
        7,
        101,
        matched_incident_id=canonical.id,
        reason=DeletedReason.cluster_subsumption,
    )

    assert retired.deleted_reason == "cluster_subsumption"
    [entry] = _added_updates(db)
    assert entry.action == UpdateAction.delete
    assert entry.performed_by is None
    assert entry.new_values["canonical_incident_id"] == str(canonical.id)


def test_reconciliation_only_considers_pipeline_deletes() -> None:
    from app.news.services.dedup.duplicate_match_reconciliation import (
        reconcile_orphaned_soft_deleted_incidents,
    )

    db = MagicMock()
    db.scalars.return_value.all.return_value = []

    reconcile_orphaned_soft_deleted_incidents(db)

    orphan_query = db.scalars.call_args_list[0].args[0]
    sql = str(
        orphan_query.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "incidents.deleted_reason IN ('duplicate_merge', 'cluster_subsumption')" in sql
