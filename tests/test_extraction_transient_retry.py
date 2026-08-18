from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from app.llm.actions.extract_incidents_action import ExtractIncidentsAction
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

    action = ExtractIncidentsAction(raw_messages=raw_messages, classifier=classifier)

    with pytest.raises(httpx.ReadTimeout):
        action.execute_one(42)

    raw_messages.save_error.assert_not_called()


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

    raw_messages.save_error.assert_called_once()
