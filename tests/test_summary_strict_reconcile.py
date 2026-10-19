"""Strict (backfill) reconcile rules against a real scratch PostgreSQL."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.news.models import Incident, IncidentOrigin, MessageStatus, RawMessage
from app.news.models.summary_bulletin import SummaryItem, SummaryReconciliationStatus, SummaryReviewTask, SummaryStatus
from app.news.services.summaries.gap_classification import GapClassifier
from app.news.services.summaries.reconcile_service import StrictContext, reconcile_summary
from tests.summary_db import BEIRUT, add_incident, add_summary, at, build_world


@pytest.fixture
def world():
    w = build_world()
    yield w
    w.session.rollback()
    w.session.close()


def strict_ctx(world, summary_ids=None) -> StrictContext:
    ids = set(summary_ids or set())
    ctx = StrictContext(summary_message_ids=ids)
    ctx.classifier = GapClassifier(world.session, summary_message_ids=ids, tolerance_minutes=settings.summary_match_tolerance_minutes)
    return ctx


def run(world, summary, ctx, dry_run=False):
    return asyncio.run(reconcile_summary(world.session, summary.id, dry_run=dry_run, strict=ctx))


def items_of(world, summary):
    return world.session.scalars(select(SummaryItem).where(SummaryItem.summary_id == summary.id).order_by(SummaryItem.position)).all()


def task_of(world, summary):
    return world.session.scalar(select(SummaryReviewTask).where(SummaryReviewTask.summary_id == summary.id))


def add_news(world, text, *, status=MessageStatus.error, when=None) -> RawMessage:
    when = when or datetime(2026, 10, 7, 9, 0, tzinfo=BEIRUT)
    raw = RawMessage(
        source_id=world.source_id, raw_text=text, raw_payload={}, status=status, source_name="خبر",
        external_message_id=f"news-{datetime.now().timestamp()}-{text}", message_datetime=when.astimezone(timezone.utc),
    )
    world.session.add(raw)
    world.session.flush()
    return raw


def incident_count(world) -> int:
    return world.session.scalar(select(func.count()).select_from(Incident)) or 0


# ---- create only for NEWS_NEVER_ARRIVED -------------------------------------

def test_never_arrived_is_created_with_decision_and_no_casualties(world):
    summary = add_summary(world, [{"village": "A"}])
    ctx = strict_ctx(world)
    run(world, summary, ctx)
    item = items_of(world, summary)[0]
    assert item.reconciliation_status == SummaryReconciliationStatus.created
    incident = world.session.get(Incident, item.created_incident_id)
    assert incident.origin == IncidentOrigin.summary and incident.decision_reason == "ACCEPTED_MISSED_NEVER_ARRIVED"
    assert incident.decision_source_summary_id == summary.id
    assert incident.deaths is None and incident.total_deaths is None
    assert ctx.changes["incident_created"] == 1


def test_news_failed_goes_to_review_and_is_listed_for_reprocess(world):
    raw = add_news(world, "غارة على كفرا قبل قليل", status=MessageStatus.error)
    summary = add_summary(world, [{"village": "A"}])
    ctx = strict_ctx(world)
    run(world, summary, ctx)
    item = items_of(world, summary)[0]
    assert item.reconciliation_status == SummaryReconciliationStatus.pending and item.created_incident_id is None
    reason = task_of(world, summary).reasons[0]
    assert reason["type"] == "news_failed" and reason["raw_message_ids"] == [raw.id]
    assert ctx.failed_raw_ids[summary.raw_message_id] == {raw.id}
    assert incident_count(world) == 0


def test_news_rejected_goes_to_review_with_raw_ids(world):
    raw = add_news(world, "غارة على كفرا", status=MessageStatus.rejected)
    summary = add_summary(world, [{"village": "A"}])
    run(world, summary, strict_ctx(world))
    reason = task_of(world, summary).reasons[0]
    assert reason["type"] == "news_rejected" and reason["raw_message_ids"] == [raw.id]
    assert incident_count(world) == 0


def test_wrong_village_is_linked_to_the_wrong_incident_for_review(world):
    raw = add_news(world, "غارة على كفرا", status=MessageStatus.materialized)
    wrong = add_incident(world, village="C", condition="Bombs", at=datetime(2026, 10, 7, 9, 0), raw_message_id=raw.id)
    summary = add_summary(world, [{"village": "A"}])
    run(world, summary, strict_ctx(world))
    reason = task_of(world, summary).reasons[0]
    assert reason["type"] == "news_wrong_village" and reason["incident_ids"] == [str(wrong.id)]
    assert incident_count(world) == 1


def test_same_village_other_action_goes_to_review(world):
    add_incident(world, village="A", condition="Flare Bomb", at=at(7, 10))
    summary = add_summary(world, [{"village": "A", "condition": "Bombs"}])
    run(world, summary, strict_ctx(world))
    assert task_of(world, summary).reasons[0]["type"] == "same_village_other_action"
    assert incident_count(world) == 1


def test_guard_blocks_creation_next_to_any_incident_at_the_village(world):
    # Outside the window and its tolerance, so not an action mismatch -- only the +-1 day guard sees it.
    near = add_incident(world, village="A", condition="Flare Bomb", at=at(6, 20, 0))
    summary = add_summary(world, [{"village": "A"}])
    run(world, summary, strict_ctx(world))
    reason = task_of(world, summary).reasons[0]
    assert reason["type"] == "nearby_incident_guard" and reason["incident_ids"] == [str(near.id)]
    assert items_of(world, summary)[0].created_incident_id is None


def test_guard_does_not_block_two_days_away(world):
    add_incident(world, village="A", condition="Flare Bomb", at=at(5, 12))
    summary = add_summary(world, [{"village": "A"}])
    run(world, summary, strict_ctx(world))
    assert items_of(world, summary)[0].reconciliation_status == SummaryReconciliationStatus.created


def test_one_review_task_per_summary_not_per_row(world):
    add_news(world, "غارة على كفرا", status=MessageStatus.error)
    add_news(world, "غارة على صديقين", status=MessageStatus.rejected)
    add_incident(world, village="C", condition="Flare Bomb", at=at(7, 10))
    summary = add_summary(world, [{"village": "A"}, {"village": "B"}, {"village": "C"}])
    run(world, summary, strict_ctx(world))
    tasks = world.session.scalars(select(SummaryReviewTask).where(SummaryReviewTask.summary_id == summary.id)).all()
    assert len(tasks) == 1
    assert sorted(r["type"] for r in tasks[0].reasons) == ["news_failed", "news_rejected", "same_village_other_action"]


def test_invalid_window_creates_and_matches_nothing(world):
    add_incident(world, village="A", condition="Bombs", at=at(7, 10))
    start = datetime(2026, 10, 7, tzinfo=BEIRUT)
    summary = add_summary(world, [{"village": "A"}, {"village": "B"}], window=(start, start))
    before_note = world.session.scalars(select(Incident.note)).all()
    ctx = strict_ctx(world)
    run(world, summary, ctx)
    assert {r["type"] for r in task_of(world, summary).reasons} == {"invalid_window"}
    assert incident_count(world) == 1 and world.session.scalars(select(Incident.note)).all() == before_note
    assert all(i.reconciliation_status == SummaryReconciliationStatus.pending for i in items_of(world, summary))


def test_short_full_day_window_is_invalid_but_short_partial_is_not(world):
    start = datetime(2026, 10, 7, tzinfo=BEIRUT)
    short_daily = add_summary(world, [{"village": "A"}], window=(start, start + timedelta(hours=1)))
    run(world, short_daily, strict_ctx(world))
    assert task_of(world, short_daily).reasons[0]["type"] == "invalid_window"


# ---- date-based dedupe -------------------------------------------------------

def test_full_day_then_partial_summary_do_not_create_two_incidents(world):
    full = add_summary(world, [{"village": "A"}], channel="قناة 1")
    ctx = strict_ctx(world)
    run(world, full, ctx)
    partial = add_summary(world, [{"village": "A"}], channel="قناة 2",
        window=(datetime(2026, 10, 7, 0, tzinfo=BEIRUT), datetime(2026, 10, 7, 8, tzinfo=BEIRUT)))
    run(world, partial, ctx)
    created = world.session.scalars(select(Incident).where(Incident.village_id == world.village["A"])).all()
    assert len(created) == 1
    assert items_of(world, partial)[0].reconciliation_status == SummaryReconciliationStatus.matched
    assert items_of(world, partial)[0].matched_incident_id == created[0].id


def test_same_village_second_action_after_a_creation_is_guarded(world):
    first = add_summary(world, [{"village": "A", "condition": "Bombs"}])
    ctx = strict_ctx(world)
    run(world, first, ctx)
    second = add_summary(world, [{"village": "A", "condition": "Flare Bomb"}], channel="قناة 2")
    run(world, second, ctx)
    assert incident_count(world) == 1
    assert task_of(world, second).reasons[0]["type"] in {"nearby_incident_guard", "same_village_other_action"}


# ---- idempotence / dry run ---------------------------------------------------

def test_second_run_changes_nothing(world):
    add_news(world, "غارة على كفرا", status=MessageStatus.error)
    add_incident(world, village="C", condition="Bombs", at=at(7, 10))
    summary = add_summary(world, [{"village": "A"}, {"village": "B"}, {"village": "C"}, {"village": "D"}])
    ctx = strict_ctx(world)
    run(world, summary, ctx)
    first_changes = dict(ctx.changes)
    assert first_changes
    snapshot = (incident_count(world), world.session.scalars(select(Incident.note).order_by(Incident.id)).all(), task_of(world, summary).reasons)
    ctx2 = strict_ctx(world)
    run(world, summary, ctx2)
    assert ctx2.changes.get("incident_created", 0) == 0 and ctx2.changes.get("confirmation_note", 0) == 0
    assert ctx2.changes.get("review_reason_added", 0) == 0 and ctx2.changes.get("review_task_created", 0) == 0
    assert (incident_count(world), world.session.scalars(select(Incident.note).order_by(Incident.id)).all(), task_of(world, summary).reasons) == snapshot


def test_dry_run_writes_only_shadow_result(world):
    add_news(world, "غارة على كفرا", status=MessageStatus.error)
    summary = add_summary(world, [{"village": "A"}, {"village": "B"}])
    ctx = strict_ctx(world)
    run(world, summary, ctx, dry_run=True)
    world.session.refresh(summary)
    assert incident_count(world) == 0 and task_of(world, summary) is None
    assert summary.shadow_result is not None and summary.status == SummaryStatus.parsed
    assert not ctx.changes


def test_confirmation_note_is_appended_once_to_a_matched_news_incident(world):
    inc = add_incident(world, village="A", condition="Bombs", at=at(7, 10), note="ملاحظة")
    summary = add_summary(world, [{"village": "A"}])
    ctx = strict_ctx(world)
    run(world, summary, ctx)
    run(world, summary, strict_ctx(world))
    world.session.refresh(inc)
    assert inc.note.count("مؤكد في ملخص") == 1 and inc.note.startswith("ملاحظة")
    assert ctx.changes["confirmation_note"] == 1


def test_casualty_items_are_never_created_from_a_summary(world):
    summary = add_summary(world, [{"village": "A", "evidence": "- كفرا استشهاد مواطن"}])
    run(world, summary, strict_ctx(world))
    assert incident_count(world) == 0 and task_of(world, summary).reasons[0]["type"] == "casualty_in_summary"
