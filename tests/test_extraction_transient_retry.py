from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from app.llm.actions.extract_incidents_action import ExtractIncidentsAction
from app.llm.services.ollama_auth_failures import OLLAMA_AUTH_ERROR_MARKER, OllamaAuthFailure
from app.llm.services.transient_llm_errors import ExtractionRetryCappedError
from app.news.models import MessageStatus


def test_execute_one_does_not_save_error_on_read_timeout() -> None:
    raw_messages = MagicMock()
    classifier = MagicMock()
    message = MagicMock()
    message.id = 42
    message.extraction_result = None
    message.status = MessageStatus.parsed
    message.raw_text = "test"
    raw_messages.get_by_id.return_value = message
    classifier.extract_tier1.side_effect = httpx.ReadTimeout("timed out")
    raw_messages.record_transient_extraction_failure.return_value = False

    action = ExtractIncidentsAction(raw_messages=raw_messages, classifier=classifier)

    with pytest.raises(httpx.ReadTimeout):
        action.execute_one(42)

    raw_messages.save_error.assert_not_called()
    raw_messages.record_transient_extraction_failure.assert_called_once()


def test_execute_one_saves_error_on_permanent_failure() -> None:
    raw_messages = MagicMock()
    classifier = MagicMock()
    message = MagicMock()
    message.id = 42
    message.extraction_result = None
    message.status = MessageStatus.parsed
    message.raw_text = "test"
    raw_messages.get_by_id.return_value = message
    classifier.extract_tier1.side_effect = RuntimeError("Malformed extraction response.")

    action = ExtractIncidentsAction(raw_messages=raw_messages, classifier=classifier)

    with pytest.raises(RuntimeError):
        action.execute_one(42)

    raw_messages.record_transient_extraction_failure.assert_not_called()


def test_execute_one_raises_capped_error_when_retry_limit_hit() -> None:
    raw_messages = MagicMock()
    classifier = MagicMock()
    message = MagicMock()
    message.id = 42
    message.extraction_result = None
    message.status = MessageStatus.parsed
    message.raw_text = "test"
    message.error_message = (
        "extraction: exceeded max retries (5) — last error: ReadTimeout: timed out"
    )
    raw_messages.get_by_id.return_value = message
    classifier.extract_tier1.side_effect = httpx.ReadTimeout("timed out")
    raw_messages.record_transient_extraction_failure.return_value = True

    action = ExtractIncidentsAction(raw_messages=raw_messages, classifier=classifier)

    with pytest.raises(ExtractionRetryCappedError):
        action.execute_one(42)

    raw_messages.save_error.assert_not_called()


def test_execute_aborts_on_401_and_leaves_remaining_messages_parsed() -> None:
    raw_messages = MagicMock()
    classifier = MagicMock()

    first = MagicMock()
    first.id = 1
    first.raw_text = "one"
    first.status = MessageStatus.parsed
    first.extraction_result = None

    second = MagicMock()
    second.id = 2
    second.raw_text = "two"
    second.status = MessageStatus.parsed
    second.extraction_result = None

    third = MagicMock()
    third.id = 3
    third.raw_text = "three"
    third.status = MessageStatus.parsed
    third.extraction_result = None

    request = httpx.Request("POST", "http://ollama.test/api/chat")
    response = httpx.Response(401, request=request)
    auth_exc = httpx.HTTPStatusError("unauthorized", request=request, response=response)

    classifier.extract_tier1.side_effect = [
        MagicMock(),
        auth_exc,
    ]
    raw_messages.get_pending_extraction_batch.return_value = [first, second, third]

    action = ExtractIncidentsAction(raw_messages=raw_messages, classifier=classifier)

    with pytest.raises(OllamaAuthFailure, match=OLLAMA_AUTH_ERROR_MARKER):
        action.execute(data=MagicMock(batch_size=10))

    raw_messages.save_extraction_result.assert_called_once()
    raw_messages.save_error.assert_not_called()
    raw_messages.record_transient_extraction_failure.assert_not_called()
    assert third.status == MessageStatus.parsed
