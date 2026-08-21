from __future__ import annotations

from types import SimpleNamespace

from unittest.mock import MagicMock

import httpx
import pytest

from app.news.models import MessageStatus
from app.news.repositories.raw_message_repository import RawMessageRepository


class _SessionStub:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commit_calls = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commit_calls += 1

    def scalars(self, _statement):
        return self

    def all(self):
        return []


def _message(*, retry_count: int = 0, status=MessageStatus.parsed) -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        status=status,
        extraction_result=None,
        error_message=None,
        extraction_retry_count=retry_count,
        raw_text="test",
    )


def test_record_transient_extraction_failure_increments_under_cap() -> None:
    db = _SessionStub()
    repo = RawMessageRepository(db)  # type: ignore[arg-type]
    message = _message(retry_count=0)

    capped = repo.record_transient_extraction_failure(
        message,  # type: ignore[arg-type]
        httpx.ReadTimeout("timed out"),
        max_retries=5,
    )

    assert capped is False
    assert message.extraction_retry_count == 1
    assert message.status == MessageStatus.error
    assert message.error_message == "ReadTimeout: timed out"
    assert db.commit_calls == 1


def test_record_transient_extraction_failure_caps_at_threshold() -> None:
    db = _SessionStub()
    repo = RawMessageRepository(db)  # type: ignore[arg-type]
    message = _message(retry_count=4)

    capped = repo.record_transient_extraction_failure(
        message,  # type: ignore[arg-type]
        httpx.ReadTimeout("timed out"),
        max_retries=5,
    )

    assert capped is True
    assert message.extraction_retry_count == 5
    assert message.status == MessageStatus.error
    assert message.error_message.startswith("extraction: exceeded max retries (5)")
    assert "ReadTimeout" in (message.error_message or "")


def test_reset_retryable_extraction_errors_respects_cap() -> None:
    db = MagicMock()
    under_cap = _message(retry_count=2, status=MessageStatus.error)
    under_cap.error_message = "httpx.ReadTimeout: timed out"
    at_cap = _message(retry_count=5, status=MessageStatus.error)
    at_cap.error_message = "httpx.ReadTimeout: timed out"

    db.scalars.return_value.all.return_value = [under_cap, at_cap]
    repo = RawMessageRepository(db)

    reset_count, capped_count = repo.reset_retryable_extraction_errors(max_retries=5)

    assert reset_count == 1
    assert capped_count == 1
    assert under_cap.status == MessageStatus.parsed
    assert under_cap.error_message is None
    assert at_cap.status == MessageStatus.error
    assert at_cap.error_message.startswith("extraction: exceeded max retries (5)")
    db.commit.assert_called_once()
