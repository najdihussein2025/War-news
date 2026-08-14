from __future__ import annotations

import os
from types import SimpleNamespace
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("CNRS_WEBHOOK_SECRET", "test-webhook-secret")

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.api.news import webhook_router
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.news import RawMessage
from app.repositories.news import SourceRepository


class _WebhookSourceRepository:
    messages: list[RawMessage] = []
    seen: set[tuple[int, str]] = set()

    def __init__(self, db=None) -> None:
        self.db = db

    @classmethod
    def reset(cls) -> None:
        cls.messages = []
        cls.seen = set()

    def get_by_id(self, source_id: int):
        return SimpleNamespace(id=source_id, name="CNRS Webhook")

    def get_active_by_external_id(self, external_id: str):
        raise NotImplementedError

    def add_raw_message(self, raw_message: RawMessage) -> None:
        key = (raw_message.source_id, raw_message.external_message_id or "")
        if key in self.seen:
            raise IntegrityError(
                statement=None,
                params=None,
                orig=Exception("uq_raw_messages_source_external_message"),
            )
        self.seen.add(key)
        self.messages.append(raw_message)

    def commit(self) -> None:
        return

    def is_duplicate_raw_message_error(self, exc: IntegrityError) -> bool:
        return "uq_raw_messages_source_external_message" in str(exc.orig)

    def update_last_cursor(self, source, cursor: str | None) -> None:
        raise NotImplementedError

    def write_ingestion_log(
        self,
        source_id: int,
        messages_fetched: int,
        messages_parsed: int,
        messages_failed: int,
        started_at: datetime,
    ) -> None:
        raise NotImplementedError

    def rollback(self) -> None:
        return


def _client() -> TestClient:
    _WebhookSourceRepository.reset()
    settings.cnrs_webhook_secret = "test-webhook-secret"
    webhook_router.SourceRepository = _WebhookSourceRepository
    app.dependency_overrides[get_db] = lambda: None
    return TestClient(app)


def _headers(secret: str = "test-webhook-secret") -> dict[str, str]:
    return {"X-Webhook-Secret": secret}


def _payload(external_message_id: str = "cnrs-1") -> dict[str, str]:
    return {
        "external_message_id": external_message_id,
        "message_datetime": "2026-08-13T10:20:30+00:00",
        "raw_text": "Post text",
        "extra_field": "preserved",
    }


def test_cnrs_metadata_is_mapped_without_inventing_missing_keys() -> None:
    client = _client()
    payload = _payload()
    payload.update(
        {
            "source_platform": "telegram",
            "source_name": "example-channel",
            "include": True,
            "confidence": 0.91,
            "location": None,
        }
    )

    response = client.post(
        "/webhooks/cnrs-posts?source_id=44",
        headers=_headers(),
        json=payload,
    )

    assert response.status_code == 202
    message = _WebhookSourceRepository.messages[0]
    assert message.source_platform == "telegram"
    assert message.source_name == "example-channel"
    assert message.origin_platform == "telegram"
    assert message.origin_account == "example-channel"
    assert message.cnrs_classification == {
        "include": True,
        "confidence": 0.91,
        "location": None,
    }


def test_valid_secret_single_post_returns_202_and_writes_raw_message() -> None:
    client = _client()

    response = client.post(
        "/webhooks/cnrs-posts?source_id=44",
        headers=_headers(),
        json=_payload(),
    )

    assert response.status_code == 202
    assert response.json() == {"received": 1, "saved": 1, "duplicates": 0}
    assert len(_WebhookSourceRepository.messages) == 1
    message = _WebhookSourceRepository.messages[0]
    assert message.source_id == 44
    assert message.external_message_id == "cnrs-1"
    assert message.raw_text == "Post text"
    assert message.raw_payload["extra_field"] == "preserved"
    assert message.message_datetime == datetime(2026, 8, 13, 10, 20, 30, tzinfo=timezone.utc)


def test_valid_secret_array_of_posts_returns_202_and_writes_all_messages() -> None:
    client = _client()

    response = client.post(
        "/webhooks/cnrs-posts?source_id=45",
        headers=_headers(),
        json=[_payload("cnrs-1"), _payload("cnrs-2")],
    )

    assert response.status_code == 202
    assert response.json() == {"received": 2, "saved": 2, "duplicates": 0}
    assert [message.external_message_id for message in _WebhookSourceRepository.messages] == [
        "cnrs-1",
        "cnrs-2",
    ]


def test_missing_or_wrong_secret_returns_401_and_writes_nothing() -> None:
    client = _client()

    missing = client.post("/webhooks/cnrs-posts?source_id=46", json=_payload())
    wrong = client.post(
        "/webhooks/cnrs-posts?source_id=46",
        headers=_headers("wrong"),
        json=_payload(),
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert _WebhookSourceRepository.messages == []


def test_duplicate_external_message_id_is_noop_not_error() -> None:
    client = _client()

    first = client.post(
        "/webhooks/cnrs-posts?source_id=47",
        headers=_headers(),
        json=_payload("duplicate-id"),
    )
    second = client.post(
        "/webhooks/cnrs-posts?source_id=47",
        headers=_headers(),
        json=_payload("duplicate-id"),
    )

    assert first.status_code == 202
    assert first.json() == {"received": 1, "saved": 1, "duplicates": 0}
    assert second.status_code == 202
    assert second.json() == {"received": 1, "saved": 0, "duplicates": 1}
    assert len(_WebhookSourceRepository.messages) == 1


def test_malformed_payload_missing_external_message_id_returns_422() -> None:
    client = _client()

    response = client.post(
        "/webhooks/cnrs-posts?source_id=48",
        headers=_headers(),
        json={
            "message_datetime": "2026-08-13T10:20:30+00:00",
            "raw_text": "Post text",
        },
    )

    assert response.status_code == 422
    assert _WebhookSourceRepository.messages == []
