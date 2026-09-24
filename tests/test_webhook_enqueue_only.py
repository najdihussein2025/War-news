"""4.3: the webhook only enqueues; LLM work runs in the pipeline worker."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.api import webhooks_router


def test_webhook_enqueues_with_advisory_lock_and_does_not_drain(monkeypatch) -> None:
    enqueued: list[dict] = []
    monkeypatch.setattr(
        webhooks_router,
        "enqueue_pipeline_sweep",
        lambda db, **kwargs: enqueued.append(kwargs),
    )
    sources = MagicMock()
    sources.get_active_by_external_id.return_value = SimpleNamespace(id=46)
    monkeypatch.setattr(webhooks_router, "SourceRepository", lambda db: sources)
    action = MagicMock()
    action.execute.return_value = {"saved": 1}
    monkeypatch.setattr(webhooks_router, "ReceiveCnrsWebhookAction", lambda **_: action)

    result = webhooks_router.receive_cnrs_posts(
        payload=MagicMock(),
        source_id=None,
        db=MagicMock(),
    )

    assert result == {"saved": 1}
    assert enqueued == [{"use_advisory_lock": True}]


def test_webhook_has_no_in_process_drain() -> None:
    parameters = inspect.signature(webhooks_router.receive_cnrs_posts).parameters
    assert "background_tasks" not in parameters
    assert not hasattr(webhooks_router, "drain_one_enqueued_pipeline_sweep_job")
