from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.sql.elements import TextClause

from app.api.deps import require_admin
from app.main import app
from app.news.services.realtime.incident_event_stream import IncidentEventStream
from app.news.services.incident_materialization_service import _notify_new_incident


INCIDENT_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def begin_nested(self):
        return nullcontext()

    def execute(self, statement: TextClause, params: dict[str, str]) -> None:
        self.calls.append((str(statement), params))


def test_notify_new_incident_publishes_expected_pg_notify_payload() -> None:
    session = FakeSession()
    incident = SimpleNamespace(
        id=INCIDENT_ID,
        raw_message_id=42,
        raw_message=SimpleNamespace(
            status=SimpleNamespace(value="materialized"),
            source_platform="telegram",
            origin_account="source-account",
            source_name=None,
            external_message_id="telegram:42",
        ),
        village_id=7,
        village=SimpleNamespace(ref_name_en="Aita al-Shaab", cad_name="Aita"),
        condition_id=3,
        condition=SimpleNamespace(action_en="Shelling", action_ar="قصف"),
        source=SimpleNamespace(type=SimpleNamespace(value="telegram")),
        event_date=date(2026, 9, 7),
        event_time=time(14, 5),
        khabar="Incident report",
        verification_status="auto_processed",
        verification_reason=None,
        verified_by_user_id=None,
        verified_at=None,
        duplicate_flag=False,
        duplicate_level=None,
        duplicate_similarity_score=None,
        details_pending=False,
        created_at=datetime(2026, 9, 7, 11, 5, tzinfo=timezone.utc),
        version=1,
        locked_by_user_id=None,
        edit_lock_expires_at=None,
    )

    _notify_new_incident(session, incident)  # type: ignore[arg-type]

    assert len(session.calls) == 1
    statement, params = session.calls[0]
    assert "pg_notify('new_incident'" in statement
    payload = json.loads(params["payload"])
    assert payload == {
        "id": str(INCIDENT_ID),
        "raw_message_id": 42,
        "raw_status": "materialized",
        "village_id": 7,
        "condition_id": 3,
        "village": "Aita al-Shaab",
        "condition": "Shelling",
        "condition_ar": "قصف",
        "event_date": "2026-09-07",
        "event_time": "14:05:00",
        "khabar": "Incident report",
        "source": "Telegram",
        "source_reference": "source-account",
        "matched": True,
        "verification_status": "auto_processed",
        "verification_reason": None,
        "verified_by_user_id": None,
        "verified_at": None,
        "duplicate_flag": "none",
        "duplicate_level": None,
        "duplicate_similarity_score": None,
        "details_pending": False,
        "created_at": "2026-09-07T11:05:00+00:00",
        "version": 1,
        "locked_by_user_id": None,
        "edit_lock_expires_at": None,
    }


@pytest.mark.asyncio
async def test_incident_event_stream_fans_out_and_unsubscribes() -> None:
    stream = IncidentEventStream(queue_size=1)
    first = await stream.subscribe()
    second = await stream.subscribe()

    await stream.broadcast("one")

    assert await first.get() == "one"
    assert await second.get() == "one"

    await stream.unsubscribe(second)
    await stream.broadcast("two")

    assert await first.get() == "two"
    assert second.empty()


def test_incident_stream_requires_authentication() -> None:
    response = TestClient(app).get("/api/incidents/stream")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_incident_stream_delivers_broadcast_to_simulated_client(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    from app.api import incidents_router

    queue: asyncio.Queue[str] = asyncio.Queue()
    queue.put_nowait('{"id":"incident-1"}')

    async def subscribe() -> asyncio.Queue[str]:
        return queue

    async def unsubscribe(_: asyncio.Queue[str]) -> None:
        return None

    monkeypatch.setattr(incidents_router.incident_event_stream, "subscribe", subscribe)
    monkeypatch.setattr(incidents_router.incident_event_stream, "unsubscribe", unsubscribe)
    async def is_disconnected() -> bool:
        return False

    request = SimpleNamespace(is_disconnected=is_disconnected)

    response = await incidents_router.stream_incidents(
        request,  # type: ignore[arg-type]
        current_user=SimpleNamespace(id=INCIDENT_ID),
    )

    assert response.media_type == "text/event-stream"
    assert await anext(response.body_iterator) == 'data: {"id":"incident-1"}\n\n'
