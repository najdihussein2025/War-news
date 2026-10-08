"""summary-reconcile-worker batch driver (scratch DB) and its compose wiring."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.news.models import Incident, MessageStatus, RawMessage
from app.news.models.summary_bulletin import (
    SummaryBulletin,
    SummaryReviewStatus,
    SummaryReviewTask,
    SummaryStatus,
)
from app.news.services.summaries.reconcile_worker import due_summary_ids, run_reconcile_batch
from tests.summary_db import add_summary, build_world


@pytest.fixture
def world():
    w = build_world()
    yield w
    w.session.rollback()
    w.session.close()


def _due(world, summary, minutes_ago: int = 5):
    summary.process_after = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    world.session.flush()
    return summary


def _factory(world):
    return lambda: Session(world.engine)


def test_live_batch_reconciles_due_summaries_and_reports_shape(world):
    due = _due(world, add_summary(world, [{"village": "A"}]))
    future = add_summary(world, [{"village": "B"}], channel="ثانية")
    future.process_after = datetime.now(timezone.utc) + timedelta(hours=1)
    world.session.commit()
    result = run_reconcile_batch(_factory(world), mode="live")
    assert {"processed", "succeeded", "failed"} <= set(result)
    assert (result["processed"], result["succeeded"], result["failed"]) == (1, 1, 0)
    world.session.expire_all()
    assert world.session.get(SummaryBulletin, due.id).status == SummaryStatus.reconciled
    assert world.session.get(SummaryBulletin, future.id).status == SummaryStatus.parsed
    assert len(world.session.scalars(select(Incident)).all()) == 1


def test_live_ignores_summaries_whose_message_tier1_also_handled(world):
    summary = _due(world, add_summary(world, [{"village": "A"}]))
    world.session.get(RawMessage, summary.raw_message_id).status = MessageStatus.parsed
    world.session.commit()
    assert due_summary_ids(world.session, mode="live") == []


def test_shadow_dry_runs_each_summary_once_and_writes_no_incidents(world):
    summary = _due(world, add_summary(world, [{"village": "A"}]))
    world.session.get(RawMessage, summary.raw_message_id).status = MessageStatus.parsed
    world.session.commit()
    first = run_reconcile_batch(_factory(world), mode="shadow")
    second = run_reconcile_batch(_factory(world), mode="shadow")
    assert (first["processed"], second["processed"]) == (1, 0)
    world.session.expire_all()
    stored = world.session.get(SummaryBulletin, summary.id)
    assert stored.shadow_result["items"][0]["outcome"] == "would_create"
    assert world.session.scalars(select(Incident)).all() == []


def test_off_mode_is_idle(world):
    _due(world, add_summary(world, [{"village": "A"}]))
    world.session.commit()
    assert run_reconcile_batch(_factory(world), mode="off")["processed"] == 0


def test_needs_review_waits_for_task_then_reprocesses_pending_items(world):
    summary = _due(world, add_summary(world, [{"village": "A"}], status=SummaryStatus.needs_review))
    task = SummaryReviewTask(summary_id=summary.id, reasons=[], status=SummaryReviewStatus.open)
    world.session.add(task)
    world.session.commit()
    assert due_summary_ids(world.session, mode="live") == []
    task.status = SummaryReviewStatus.resolved
    world.session.commit()
    assert due_summary_ids(world.session, mode="live") == [summary.id]


def test_failed_attempts_stop_the_retry_loop(world):
    summary = _due(world, add_summary(world, [{"village": "A"}]))
    summary.attempts = 5
    world.session.commit()
    assert due_summary_ids(world.session, mode="live") == []


def test_worker_is_wired_in_both_compose_files_like_the_other_workers():
    base = Path("docker-compose.yml").read_text(encoding="utf-8").replace(chr(13) + chr(10), chr(10))
    dev = Path("docker-compose.dev.yml").read_text(encoding="utf-8").replace(chr(13) + chr(10), chr(10))
    assert "summary-reconcile-worker:" in base and "summary-reconcile-worker:" in dev
    block = base.split("summary-reconcile-worker:")[1].split("\n\n")[0]
    assert "python -m scripts.summary_reconcile_sweep" in block
    assert "SUMMARY_RECONCILE_INTERVAL_SECONDS" in block and "PYTHONUNBUFFERED" in block
    assert "volumes:" not in block, "deploy workers must not bind-mount the source tree"
    assert "volumes:" in dev.split("summary-reconcile-worker:")[1].split("\n\n")[0]
