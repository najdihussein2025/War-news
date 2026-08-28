from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.news.models import MessageStatus
from app.news.repositories.raw_message_repository import (
    MATCHING_RETRY_CAP_PREFIX,
    RawMessageRepository,
)


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
        extraction_result={"ok": True},
        match_result=None,
        error_message=None,
        extraction_retry_count=0,
        match_retry_count=retry_count,
        processing_claim_stage="matching",
        processing_claimed_at="claimed-now",
        processing_claimed_by="worker-1",
        raw_text="test",
    )


def test_record_transient_matching_failure_increments_under_cap() -> None:
    db = _SessionStub()
    repo = RawMessageRepository(db)  # type: ignore[arg-type]
    message = _message(retry_count=0)

    capped = repo.record_transient_matching_failure(
        message,  # type: ignore[arg-type]
        RuntimeError("match blew up"),
        max_retries=5,
    )

    assert capped is False
    assert message.match_retry_count == 1
    assert message.status == MessageStatus.error
    assert message.error_message == "RuntimeError: match blew up"
    assert message.processing_claim_stage is None
    assert message.processing_claimed_at is None
    assert message.processing_claimed_by is None
    assert db.commit_calls == 1


def test_record_transient_matching_failure_caps_at_threshold() -> None:
    db = _SessionStub()
    repo = RawMessageRepository(db)  # type: ignore[arg-type]
    message = _message(retry_count=4)

    capped = repo.record_transient_matching_failure(
        message,  # type: ignore[arg-type]
        RuntimeError("match blew up"),
        max_retries=5,
    )

    assert capped is True
    assert message.match_retry_count == 5
    assert message.status == MessageStatus.error
    assert message.error_message.startswith("matching: exceeded max retries (5)")
    assert "RuntimeError" in (message.error_message or "")


def test_reset_retryable_matching_errors_respects_cap() -> None:
    db = MagicMock()
    under_cap = _message(retry_count=2, status=MessageStatus.error)
    under_cap.error_message = "RuntimeError: match blew up"
    at_cap = _message(retry_count=5, status=MessageStatus.error)
    at_cap.error_message = "RuntimeError: match blew up"

    db.scalars.return_value.all.return_value = [under_cap, at_cap]
    repo = RawMessageRepository(db)

    reset_count, capped_count = repo.reset_retryable_matching_errors(max_retries=5)

    assert reset_count == 1
    assert capped_count == 1
    assert under_cap.status == MessageStatus.parsed
    assert under_cap.error_message is None
    assert under_cap.processing_claim_stage is None
    assert under_cap.processing_claimed_at is None
    assert under_cap.processing_claimed_by is None
    assert at_cap.status == MessageStatus.error
    assert at_cap.error_message.startswith(MATCHING_RETRY_CAP_PREFIX)
    db.commit.assert_called_once()
