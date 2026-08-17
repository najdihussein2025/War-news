import os
from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

import app.api.incidents_router as incidents_router_module
from app.api.deps import require_admin
from app.core.database import get_db
from app.main import app
from app.news.dtos import CasualtyDemographicsDTO, IncidentDetailDTO
from app.news.models import Condition, Incident, IncidentDetail, RawMessage, Village
from app.news.repositories import IncidentRepository
from app.sources.models import Source, SourceType

INCIDENT_ID = UUID("11111111-1111-4111-8111-111111111111")


def _detail_dto() -> IncidentDetailDTO:
    return IncidentDetailDTO(
        id=INCIDENT_ID,
        village="Aitaroun",
        condition="Shelling",
        source="API",
        source_reference="source-42",
        khabar="A real incident report.",
        note=None,
        moh=None,
        martyrs=None,
        worker_name=None,
        source_link=None,
        source_link_2=None,
        total_deaths=1,
        total_injuries=2,
        deaths=1,
        injuries=2,
        event_date=date(2026, 8, 17),
        event_time=time(10, 30),
        created_at=datetime(2026, 8, 17, 11, 0, tzinfo=timezone.utc),
        matched=False,
        duplicate_flag="possible",
        casualty_demographics=CasualtyDemographicsDTO(
            male_d=1,
            male_i=2,
            female_d=None,
            female_i=None,
            children_d=None,
            children_i=None,
        ),
    )


class _IncidentRepository:
    def __init__(self, _db=None) -> None:
        pass

    def get_by_id(self, incident_id: UUID) -> IncidentDetailDTO | None:
        return _detail_dto() if incident_id == INCIDENT_ID else None


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        incidents_router_module,
        "IncidentRepository",
        _IncidentRepository,
    )
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace()
    return TestClient(app)


def test_get_incident_endpoint_returns_joined_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch)
    try:
        response = client.get(f"/api/incidents/{INCIDENT_ID}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["village"] == "Aitaroun"
    assert payload["matched"] is False
    assert payload["duplicate_flag"] == "possible"
    assert payload["casualty_demographics"]["male_d"] == 1
    assert payload["lebanese_army"] is None
    assert payload["warning_classification"] is None


def test_get_incident_endpoint_returns_404_for_missing_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch)
    try:
        response = client.get(f"/api/incidents/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {"detail": "Incident not found."}


def test_repository_get_by_id_returns_detail_and_hides_soft_deleted() -> None:
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
        source = Source(type=SourceType.api, name=f"Incident source {marker}", config={})
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

        raw_message = RawMessage(
            source_id=source.id,
            external_message_id=f"message-{marker}",
            raw_payload={},
            match_result={
                "village_match_status": "matched",
                "condition_match_status": "matched_low_confidence",
            },
            received_at=datetime.now(timezone.utc),
        )
        db.add(raw_message)
        db.flush()

        incident = Incident(
            raw_message_id=raw_message.id,
            village_id=village.id,
            condition_id=condition.id,
            source_id=source.id,
            event_date=date(2026, 8, 17),
            event_time=time(9, 45),
            khabar="Repository detail test",
            duplicate_flag=True,
        )
        db.add(incident)
        db.flush()
        db.add(
            IncidentDetail(
                incident_id=incident.id,
                male_d=1,
                children_i=2,
            )
        )
        db.flush()

        result = IncidentRepository(db).get_by_id(incident.id)

        assert result is not None
        assert result.village == village.ref_name_en
        assert result.condition == condition.action_en
        assert result.source == "API"
        assert result.source_reference == raw_message.external_message_id
        assert result.matched is False
        assert result.duplicate_flag == "possible"
        assert result.casualty_demographics.male_d == 1
        assert result.casualty_demographics.children_i == 2
        assert result.lebanese_army is None

        incident.is_deleted = True
        db.flush()
        assert IncidentRepository(db).get_by_id(incident.id) is None
    except (OperationalError, ProgrammingError) as exc:
        pytest.skip(f"Incident detail schema is unavailable: {exc}")
    finally:
        db.close()
        transaction.rollback()
        connection.close()
