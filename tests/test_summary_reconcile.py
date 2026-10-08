"""Summary reconciliation against a real (scratch) PostgreSQL."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.news.models import Incident, IncidentOrigin
from app.news.models.summary_bulletin import (
    SummaryItem,
    SummaryReconciliationStatus,
    SummaryReviewTask,
    SummaryStatus,
)
from app.news.services.summaries.condition_families import ConditionFamilies, load_family_names
from app.news.services.summaries.reconcile_service import (
    BEIRUT,
    has_casualty_words,
    reconcile_summary,
    window_midpoint,
)
from tests.summary_db import add_incident, add_summary, at, build_world


@pytest.fixture
def world():
    w = build_world()
    yield w
    w.session.rollback()
    w.session.close()


def run(session, summary, dry_run=False):
    return asyncio.run(reconcile_summary(session, summary.id, dry_run=dry_run))


def items_of(session, summary):
    return session.scalars(
        select(SummaryItem).where(SummaryItem.summary_id == summary.id).order_by(SummaryItem.position)
    ).all()


# ---- pure helpers (no DB) -------------------------------------------------

def test_families_match_by_name_and_ignore_unknown_names():
    families = ConditionFamilies.from_names(
        {"strike": ["Bombs", "Warning Raid", "Missing"]}, {"Bombs": 1, "Warning Raid": 2, "X": 3}
    )
    assert families.same(1, 2) and families.same(2, 1) and families.same(1, 1)
    assert not families.same(1, 3)
    assert families.equivalents(3) == frozenset({3})


def test_families_yaml_names_are_unique_across_families():
    names = [n for members in load_family_names().values() for n in members]
    assert len(names) == len(set(names)), "a condition may belong to only one family"


def test_midpoint_is_inside_window_even_if_inverted():
    start, end = datetime(2026, 10, 7, tzinfo=BEIRUT), datetime(2026, 10, 8, tzinfo=BEIRUT)
    assert window_midpoint(start, end) == start + timedelta(hours=12)
    assert start <= window_midpoint(end, start) <= end


@pytest.mark.parametrize("text", ["استشهاد مواطن", "سقوط جرحى", "إصابة مدني", "قتيل", "الشهداء"])
def test_casualty_words_detected(text):
    assert has_casualty_words(text)


def test_casualty_words_not_triggered_by_plain_strike_text():
    assert not has_casualty_words("الغارات", "- كفرا", "بين صور وقانا")


# ---- matching --------------------------------------------------------------

def test_matched_exact_condition_adds_one_note_and_changes_nothing_else(world):
    inc = add_incident(world, village="A", condition="Bombs", at=at(7, 10), total_deaths=2, deaths=2)
    summary = add_summary(world, [{"village": "A"}])
    result = run(world.session, summary)
    world.session.refresh(inc)
    item = items_of(world.session, summary)[0]
    assert item.reconciliation_status == SummaryReconciliationStatus.matched
    assert item.matched_incident_id == inc.id
    assert "مؤكد في ملخص قناة اختبار بتاريخ 2026-10-08" in inc.note
    assert (inc.total_deaths, inc.deaths, inc.condition_id) == (2, 2, world.condition["Bombs"])
    assert result.counts == {"matched": 1}


def test_matched_same_family(world):
    inc = add_incident(world, village="A", condition="Warning Raid", at=at(7, 10))
    summary = add_summary(world, [{"village": "A", "condition": "Bombs"}])
    run(world.session, summary)
    assert items_of(world.session, summary)[0].matched_incident_id == inc.id


def test_unrelated_condition_at_same_village_is_created(world):
    add_incident(world, village="A", condition="Flare Bomb", at=at(7, 10))
    summary = add_summary(world, [{"village": "A", "condition": "Bombs"}])
    run(world.session, summary)
    item = items_of(world.session, summary)[0]
    assert item.reconciliation_status == SummaryReconciliationStatus.created
    assert item.created_incident_id


def test_outside_window_is_created(world):
    add_incident(world, village="A", condition="Bombs", at=at(5, 10))
    summary = add_summary(world, [{"village": "A"}])
    run(world.session, summary)
    assert items_of(world.session, summary)[0].reconciliation_status == SummaryReconciliationStatus.created


def test_tolerance_catches_incident_just_outside_window(world):
    add_incident(world, village="A", condition="Bombs", at=at(8, 0, 30))  # 30 min after window end
    summary = add_summary(world, [{"village": "A"}])
    run(world.session, summary)
    assert items_of(world.session, summary)[0].reconciliation_status == SummaryReconciliationStatus.matched


def test_between_matches_on_secondary_village(world):
    inc = add_incident(world, village="B", condition="Bombs", at=at(7, 9))
    summary = add_summary(world, [{"village": "A", "secondary": "B", "location": "بين A و B"}])
    run(world.session, summary)
    assert items_of(world.session, summary)[0].matched_incident_id == inc.id


def test_earliest_of_several_is_linked(world):
    late = add_incident(world, village="A", condition="Bombs", at=at(7, 20))
    early = add_incident(world, village="A", condition="Bombs", at=at(7, 6))
    summary = add_summary(world, [{"village": "A"}])
    run(world.session, summary)
    linked = items_of(world.session, summary)[0].matched_incident_id
    assert linked == early.id and linked != late.id


def test_deleted_and_rejected_incidents_do_not_match(world):
    add_incident(world, village="A", condition="Bombs", at=at(7, 10), is_deleted=True)
    add_incident(world, village="A", condition="Bombs", at=at(7, 11), verification_status="rejected")
    summary = add_summary(world, [{"village": "A"}])
    run(world.session, summary)
    assert items_of(world.session, summary)[0].reconciliation_status == SummaryReconciliationStatus.created


def test_overlapping_partial_and_full_day_summaries_do_not_duplicate(world):
    partial = add_summary(
        world, [{"village": "A"}], window=(world.window_start, world.window_start + timedelta(hours=14))
    )
    run(world.session, partial)
    full = add_summary(world, [{"village": "A"}], channel="قناة ثانية")
    run(world.session, full)
    incidents = world.session.scalars(select(Incident).where(Incident.village_id == world.village["A"])).all()
    assert len(incidents) == 1 and incidents[0].origin == IncidentOrigin.summary
    assert items_of(world.session, full)[0].matched_incident_id == incidents[0].id
    assert "قناة ثانية" in incidents[0].note


def test_confirmation_note_is_idempotent(world):
    inc = add_incident(world, village="A", condition="Bombs", at=at(7, 10))
    summary = add_summary(world, [{"village": "A"}])
    run(world.session, summary)
    note_after_first = inc.note
    item = items_of(world.session, summary)[0]
    item.reconciliation_status = SummaryReconciliationStatus.pending  # force a second pass
    world.session.flush()
    run(world.session, summary)
    world.session.refresh(inc)
    assert inc.note == note_after_first
    assert inc.note.count("مؤكد في ملخص") == 1


# ---- creation ---------------------------------------------------------------

def test_created_incident_shape(world):
    summary = add_summary(
        world,
        [{"village": "A", "secondary": "B", "location": "بين A و B", "reported_count": 3, "evidence": "- بين A و B (٣)"}],
    )
    run(world.session, summary)
    inc = world.session.scalar(select(Incident))
    item = items_of(world.session, summary)[0]
    assert inc.origin == IncidentOrigin.summary and inc.source_summary_item_id == item.id
    assert inc.village_id == world.village["A"] and inc.raw_message_id is None
    assert (inc.deaths, inc.injuries, inc.total_deaths, inc.total_injuries) == (None, None, None, None)
    assert inc.verification_status == "auto_processed" and not inc.duplicate_flag
    assert "(×3 حسب الملخص)" in inc.note
    assert "بين A و B" in inc.note and "- بين A و B (٣)" in inc.note
    assert "نافذة الملخص" in inc.note
    assert (inc.event_date, inc.event_time.hour) == (datetime(2026, 10, 7).date(), 12)  # window midpoint


def test_casualty_words_go_to_review_and_create_nothing(world):
    summary = add_summary(world, [{"village": "A", "evidence": "- A استشهاد مواطن"}, {"village": "B"}])
    result = run(world.session, summary)
    assert len(world.session.scalars(select(Incident)).all()) == 1  # only B
    task = world.session.scalar(select(SummaryReviewTask).where(SummaryReviewTask.summary_id == summary.id))
    assert task is not None and task.reasons[0]["type"] == "casualty_in_summary"
    assert items_of(world.session, summary)[0].reconciliation_status == SummaryReconciliationStatus.pending
    assert result.outcome == "needs_review"
    assert summary.status == SummaryStatus.needs_review and not summary.hidden


def test_fully_matched_summary_is_hidden(world):
    add_incident(world, village="A", condition="Bombs", at=at(7, 10))
    add_incident(world, village="B", condition="Bombs", at=at(7, 11))
    summary = add_summary(world, [{"village": "A"}, {"village": "B"}])
    result = run(world.session, summary)
    assert result.hidden and summary.hidden and summary.status == SummaryStatus.reconciled


def test_summary_with_a_created_item_is_not_hidden(world):
    add_incident(world, village="A", condition="Bombs", at=at(7, 10))
    summary = add_summary(world, [{"village": "A"}, {"village": "B"}])
    run(world.session, summary)
    assert not summary.hidden and summary.status == SummaryStatus.reconciled


def test_rerun_after_completion_creates_nothing_new(world):
    summary = add_summary(world, [{"village": "A"}])
    run(world.session, summary)
    run(world.session, summary)
    assert len(world.session.scalars(select(Incident)).all()) == 1


def test_dry_run_writes_only_shadow_result(world):
    inc = add_incident(world, village="A", condition="Bombs", at=at(7, 10))
    summary = add_summary(world, [{"village": "A"}, {"village": "B"}])
    note_before = inc.note
    result = run(world.session, summary, dry_run=True)
    world.session.refresh(inc)
    assert inc.note == note_before
    assert len(world.session.scalars(select(Incident)).all()) == 1
    assert all(i.reconciliation_status == SummaryReconciliationStatus.pending for i in items_of(world.session, summary))
    assert summary.status == SummaryStatus.parsed and not summary.hidden
    assert {i["outcome"] for i in summary.shadow_result["items"]} == {"matched", "would_create"}
    assert result.dry_run
    assert summary.shadow_result["items"][0]["incident_id"] == str(inc.id)


def test_failed_summary_is_not_reconciled(world):
    failed = add_summary(world, [{"village": "A"}], status=SummaryStatus.failed)
    assert run(world.session, failed).outcome == "skipped_not_canonical"
    assert world.session.scalars(select(Incident)).all() == []


# ---- concurrency ------------------------------------------------------------

def test_skip_locked_two_sessions_one_processes(world):
    summary = add_summary(world, [{"village": "A"}])
    world.session.commit()
    other = Session(world.engine)
    try:
        first = run(world.session, summary)  # holds the row lock: not committed yet
        second = asyncio.run(reconcile_summary(other, summary.id, dry_run=False))
        assert first.outcome == "reconciled" and second.outcome == "skipped_locked"
        world.session.commit()
        assert len(world.session.scalars(select(Incident)).all()) == 1
    finally:
        other.rollback()
        other.close()
