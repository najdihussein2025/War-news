from datetime import date, datetime, timezone
from uuid import uuid4

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.news.dtos import IncidentListItemDTO, IncidentListParams
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


class _ListResult:
    def all(self) -> list[object]:
        return []


class _ListSessionStub:
    def __init__(self) -> None:
        self.statements: list[object] = []

    def execute(self, statement: object) -> _ListResult:
        self.statements.append(statement)
        return _ListResult()

    def scalar(self, _statement: object) -> int:
        return 0


def test_list_all_defaults_to_newest_created_first() -> None:
    db = _ListSessionStub()

    IncidentRepository(db).list_all(IncidentListParams())  # type: ignore[arg-type]

    compiled = str(
        db.statements[0].compile(compile_kwargs={"literal_binds": True})
    ).lower()
    order_at = compiled.index("order by")
    created_at = compiled.index(
        "coalesce(incidents.created_at, raw_messages.received_at)",
        order_at,
    )
    event_date_at = compiled.index("incidents.event_date", order_at)
    assert created_at < event_date_at
    assert (
        "coalesce(incidents.created_at, raw_messages.received_at) desc"
        in compiled
    )


def test_list_all_default_does_not_require_materialized_incident() -> None:
    db = _ListSessionStub()

    IncidentRepository(db).list_all(IncidentListParams())  # type: ignore[arg-type]

    compiled = str(
        db.statements[0].compile(compile_kwargs={"literal_binds": True})
    ).lower()
    assert "from raw_messages" in compiled
    assert (
        "raw_messages.status in ('parsed', 'materialized')"
        in compiled
    )
    assert "incidents.id is not null" not in compiled


def test_list_all_excludes_ocr_payload_rows() -> None:
    db = _ListSessionStub()

    IncidentRepository(db).list_all(IncidentListParams())  # type: ignore[arg-type]

    compiled = str(
        db.statements[0].compile(compile_kwargs={"literal_binds": True})
    ).lower()
    assert "not (raw_messages.raw_payload ? 'ocr_text')" in compiled


def test_list_all_incident_scoped_filters_require_materialized_incident() -> None:
    db = _ListSessionStub()

    IncidentRepository(db).list_all(  # type: ignore[arg-type]
        IncidentListParams(village="Aitaroun")
    )

    compiled = str(
        db.statements[0].compile(compile_kwargs={"literal_binds": True})
    ).lower()
    assert "incidents.id is not null" in compiled


def test_incident_list_item_accepts_pre_materialization_row() -> None:
    item = IncidentListItemDTO.model_validate(
        {
            "id": None,
            "raw_message_id": 42,
            "raw_status": "parsed",
            "village": None,
            "condition": None,
            "event_date": date(2026, 8, 28),
            "event_time": None,
            "khabar": "Incoming report still in processing.",
            "source": "Telegram",
            "source_reference": "source-channel",
            "matched": False,
            "duplicate_flag": "none",
            "details_pending": True,
            "created_at": datetime(2026, 8, 28, 9, 30, tzinfo=timezone.utc),
            "version": 1,
            "locked_by_user_id": None,
            "edit_lock_expires_at": None,
        }
    )

    assert item.id is None
    assert item.raw_message_id == 42
    assert item.raw_status == "parsed"


def test_list_duplicate_candidates_excludes_same_raw_message_when_requested() -> None:
    db = _ListSessionStub()

    IncidentRepository(db).list_duplicate_candidates(  # type: ignore[arg-type]
        village_id=976,
        event_date=date(2026, 8, 28),
        khabar_embedding=[0.1, 0.2, 0.3],
        window_days=2,
        exclude_raw_message_id=42,
    )

    compiled = str(
        db.statements[0].compile(compile_kwargs={"literal_binds": True})
    ).lower()
    assert "incidents.village_id = 976" in compiled
    assert "incidents.raw_message_id != 42" in compiled
