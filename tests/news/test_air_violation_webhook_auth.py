from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.sources.services.webhook_auth import verify_air_violation_webhook_secret


def test_air_violation_webhook_rejects_requests_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "air_violation_webhook_enabled", False)

    with pytest.raises(HTTPException) as exc_info:
        verify_air_violation_webhook_secret("test-secret")

    assert exc_info.value.status_code == 503


def test_air_violation_webhook_rejects_invalid_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "air_violation_webhook_enabled", True)
    monkeypatch.setattr(settings, "air_violation_webhook_secret", "test-secret")

    with pytest.raises(HTTPException) as exc_info:
        verify_air_violation_webhook_secret("wrong-secret")

    assert exc_info.value.status_code == 401


def test_air_violation_webhook_accepts_valid_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "air_violation_webhook_enabled", True)
    monkeypatch.setattr(settings, "air_violation_webhook_secret", "test-secret")

    assert verify_air_violation_webhook_secret("test-secret") is None
