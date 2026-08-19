from __future__ import annotations

import os
from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

import app.api.incidents_router as incidents_router_module
from app.api.deps import require_admin
from app.core.database import get_db
from app.main import app
from app.news.models import Condition, Incident, IncidentDetail, IncidentUpdate, RawMessage, UpdateAction, Village
from app.news.repositories import IncidentRepository
from app.news.services.incident_detail_edit_service import (
    IncidentDetailEditError,
    apply_incident_detail_edits,
)
from app.sources.models import Source, SourceType

INCIDENT_ID = UUID("22222222-2222-4222-8222-222222222222")
USER_ID = UUID("33333333-3333-4333-8333-333333333333")


def test_apply_edits_updates_lam_d_and_la_td_rollup() -> None:
    detail = IncidentDetail(
        incident_id=uuid4(),
        la=True,
        la_did="D",
        lam_d=1,
        laf_d=1,
        la_td=2,
    )
    incident = Incident(
        id=detail.incident_id,
        village_id=1,
        condition_id=1,
        event_date=date(2026, 8, 17),
        khabar="test",
    )

    old_values, new_values = apply_incident_detail_edits(
        incident,
        detail,
        {"lam_d": 3},
    )

    assert detail.lam_d == 3
    assert detail.la_td == 4
    assert old_values["lam_d"] == 1
    assert new_values["lam_d"] == 3
    assert old_values["la_td"] == 2
    assert new_values["la_td"] == 4


def test_apply_edits_activates_previously_empty_section() -> None:
    detail = IncidentDetail(incident_id=uuid4())
    incident = Incident(
        id=detail.incident_id,
        village_id=1,
        condition_id=1,
        event_date=date(2026, 8, 17),
        khabar="test",
    )

    old_values, new_values = apply_incident_detail_edits(
        incident,
        detail,
        {"hosp": 1, "hos_did": "D", "hos_n": "South Hospital"},
    )

    assert detail.hosp is True
    assert detail.hos_did.value == "D"
    assert detail.hos_n == "South Hospital"
    assert old_values["hosp"] is None
    assert new_values["hosp"] == 1
    assert new_values["hos_did"] == "D"
    assert new_values["hos_n"] == "South Hospital"


def test_apply_edits_rejects_did_when_gate_off() -> None:
    detail = IncidentDetail(incident_id=uuid4(), la=False)
    incident = Incident(
        id=detail.incident_id,
        village_id=1,
        condition_id=1,
        event_date=date(2026, 8, 17),
        khabar="test",
    )

    with pytest.raises(IncidentDetailEditError, match="la_did cannot be set"):
        apply_incident_detail_edits(incident, detail, {"la_did": "D"})


def test_apply_edits_rejects_automated_total_con() -> None:
    detail = IncidentDetail(incident_id=uuid4(), con_veh=True)
    incident = Incident(
        id=detail.incident_id,
        village_id=1,
        condition_id=1,
        event_date=date(2026, 8, 17),
        khabar="test",
    )

    with pytest.raises(IncidentDetailEditError, match="Automated fields"):
        apply_incident_detail_edits(incident, detail, {"total_con": 5})


def test_apply_edits_rejects_gate_off_with_orphan_dependents() -> None:
    detail = IncidentDetail(
        incident_id=uuid4(),
        la=True,
        la_did="D",
        lam_d=2,
    )
    incident = Incident(
        id=detail.incident_id,
        village_id=1,
        condition_id=1,
        event_date=date(2026, 8, 17),
        khabar="test",
    )

    with pytest.raises(IncidentDetailEditError, match="dependent fields must also be cleared"):
        apply_incident_detail_edits(
            incident,
            detail,
            {"la": 0, "lam_d": 2},
        )


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    class _Repo:
        def __init__(self, _db=None) -> None:
            pass

        def update_details(self, incident_id, fields, performed_by):
            assert performed_by == USER_ID
            assert fields == {"lam_d": 4}
            from app.news.dtos import CasualtyDemographicsDTO, IncidentDetailDTO

            return IncidentDetailDTO(
                id=incident_id,
                village="Aitaroun",
                condition="Shelling",
                source="Manual",
                source_reference=None,
                khabar="Report",
                note=None,
                moh=None,
                martyrs=None,
                worker_name=None,
                source_link=None,
                source_link_2=None,
                total_deaths=4,
                total_injuries=None,
                deaths=None,
                injuries=None,
                event_date=date(2026, 8, 17),
                event_time=None,
                created_at=datetime(2026, 8, 17, tzinfo=timezone.utc),
                matched=True,
                duplicate_flag="none",
                casualty_demographics=CasualtyDemographicsDTO(
                    male_d=None,
                    male_i=None,
                    female_d=None,
                    female_i=None,
                    children_d=None,
                    children_i=None,
                ),
                lebanese_army={"la": 1, "la_did": "D", "lam_d": 4, "la_td": 4},
            )

    monkeypatch.setattr(incidents_router_module, "IncidentRepository", _Repo)
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=USER_ID)
    return TestClient(app)


def test_patch_incident_details_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    try:
        response = client.patch(
            f"/api/incidents/{INCIDENT_ID}/details",
            json={"fields": {"lam_d": 4}},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["lebanese_army"]["lam_d"] == 4


def test_repository_update_details_writes_audit_row() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for repository integration coverage.")

    engine = create_engine(database_url)
    try:
        connection = engine.connect()
    except OperationalError as exc:
        pytest.skip(f"Database is unavailable: {exc}")

    transaction = connection.begin()
    db = Session(bind=connection)
    marker = uuid4().hex
    try:
        source = Source(type=SourceType.manual, name=f"Edit source {marker}", config={})
        village = Village(
            acs_code=int(marker[:7], 16),
            ref_name_en=f"Village {marker}",
        )
        condition = Condition(
            action_en=f"Condition {marker}",
            action_ar=f"حالة {marker}",
        )
        db.add_all([source, village, condition])
        db.flush()

        incident = Incident(
            village_id=village.id,
            condition_id=condition.id,
            source_id=source.id,
            event_date=date(2026, 8, 17),
            khabar="Edit test",
        )
        db.add(incident)
        db.flush()
        db.add(
            IncidentDetail(
                incident_id=incident.id,
                la=True,
                la_did="D",
                lam_d=2,
                la_td=2,
            )
        )
        db.flush()

        from app.accounts.models import User

        user = db.scalar(select(User).limit(1))
        if user is None:
            pytest.skip("No users in database for performed_by FK.")

        result = IncidentRepository(db).update_details(
            incident.id,
            {"lam_d": 5},
            user.id,
        )

        assert result is not None
        assert result.lebanese_army is not None
        assert result.lebanese_army.lam_d == 5
        assert result.lebanese_army.la_td == 5

        audit_row = db.scalar(
            select(IncidentUpdate)
            .where(IncidentUpdate.incident_id == incident.id)
            .order_by(IncidentUpdate.id.desc())
        )
        assert audit_row is not None
        assert audit_row.action == UpdateAction.edit
        assert audit_row.performed_by == user.id
        assert audit_row.old_values["lam_d"] == 2
        assert audit_row.new_values["lam_d"] == 5
        assert audit_row.old_values["la_td"] == 2
        assert audit_row.new_values["la_td"] == 5

        deleted = Incident(
            village_id=village.id,
            condition_id=condition.id,
            source_id=source.id,
            event_date=date(2026, 8, 17),
            khabar="Deleted",
            is_deleted=True,
        )
        db.add(deleted)
        db.flush()
        db.add(IncidentDetail(incident_id=deleted.id, la=True))
        db.flush()

        assert (
            IncidentRepository(db).update_details(deleted.id, {"lam_d": 1}, user.id)
            is None
        )
    except (OperationalError, ProgrammingError) as exc:
        pytest.skip(f"Incident detail edit schema is unavailable: {exc}")
    finally:
        db.close()
        transaction.rollback()
        connection.close()
