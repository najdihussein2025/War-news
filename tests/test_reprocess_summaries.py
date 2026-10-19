"""Backfill script: phases, dry-run parity, strict creation and idempotence on a scratch PostgreSQL."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.news.models import Condition, Incident, IncidentOrigin, IncidentUpdate, MessageStatus, RawMessage
from app.news.models.summary_bulletin import SummaryBulletin, SummaryReviewTask
from scripts.reprocess_summaries import (
    classify_old_incidents,
    run_backfill,
    select_candidate_messages,
    verify_against,
    write_outputs,
)
from tests.summary_db import BEIRUT, build_world

BULLETIN = (
    "ملخص الاعتداءات\n"
    "الغارات:\n"
    "- كفرا\n"
    "- صديقين\n"
)
POSTED = datetime(2026, 10, 7, 14, 0, tzinfo=BEIRUT)


@pytest.fixture
def world():
    w = build_world()
    # The real summary_headers.yaml maps "الغارات" to the production condition id 46
    # ("Bombs" / قصف وغارات); the scratch world's auto-increment ids rarely land on 46,
    # so this test, which runs the real parser end to end, inserts that id explicitly.
    w.session.add(Condition(id=46, action_en="Bombs", action_ar="قصف وغارات"))
    w.session.flush()
    w.condition["Bombs"] = 46
    yield w
    w.session.rollback()
    w.session.close()


LEGACY_CONSTRAINT = "ck_incidents_deleted_has_reason"


@pytest.fixture
def legacy_world(world):
    """Production holds rows deleted before reasons were recorded; the guard is NOT VALID there."""
    world.session.execute(text(f"ALTER TABLE incidents DROP CONSTRAINT IF EXISTS {LEGACY_CONSTRAINT}"))
    world.session.commit()
    yield world
    world.session.rollback()
    with world.engine.begin() as conn:
        conn.execute(text("TRUNCATE incidents CASCADE"))
        conn.execute(text(f"ALTER TABLE incidents ADD CONSTRAINT {LEGACY_CONSTRAINT} CHECK (is_deleted = false OR deleted_reason IS NOT NULL) NOT VALID"))


def _raw(world, *, text=BULLETIN, when=POSTED, name="قناة اختبار", status=MessageStatus.materialized) -> RawMessage:
    raw = RawMessage(
        source_id=world.source_id, raw_text=text, raw_payload={}, status=status,
        external_message_id=f"backfill-{when.timestamp()}-{name}-{len(text)}", source_name=name,
        message_datetime=when.astimezone(timezone.utc),
    )
    world.session.add(raw)
    world.session.flush()
    return raw


def _row(world, raw, *, village="A", condition="Bombs", deleted=False, note=None, **kwargs) -> Incident:
    incident = Incident(
        raw_message_id=raw.id, village_id=world.village[village], condition_id=world.condition[condition],
        event_date=POSTED.date(), event_time=POSTED.time(), khabar="خبر قديم", source_id=world.source_id,
        origin=IncidentOrigin.live, note=note, is_deleted=deleted, **kwargs,
    )
    world.session.add(incident)
    world.session.flush()
    return incident


def _run(world, *, apply, ids=None):
    world.session.commit()
    ids = ids or select_candidate_messages(world.session, date(2026, 10, 1), date(2026, 10, 31), None)
    state = run_backfill(world.session, ids, apply=apply, crosscheck=False, batch=50)
    if apply:
        world.session.commit()
    return state


def _fresh(world, incident):
    world.session.expire_all()
    return world.session.get(Incident, incident.id)


def test_select_candidate_messages_includes_every_message_in_range(world):
    summary = _raw(world)
    other = _raw(world, text="خبر عادي بدون ملخص", when=POSTED + timedelta(minutes=1))
    outside = _raw(world, when=POSTED + timedelta(days=40))
    ids = select_candidate_messages(world.session, date(2026, 10, 1), date(2026, 10, 31), None)
    assert summary.id in ids and other.id in ids and outside.id not in ids


def test_non_summary_message_is_skipped(world):
    _raw(world, text="خبر عادي: قصف على كفرا")
    state = _run(world, apply=False)
    world.session.rollback()
    assert state.results == {}
    assert world.session.scalars(select(SummaryBulletin)).all() == []


def test_dry_run_decides_but_writes_nothing(world):
    raw = _raw(world)
    unique = _row(world, raw, village="A")
    wrong = _row(world, raw, village="D", condition="Flare Bomb")
    state = _run(world, apply=False)
    world.session.rollback()
    by_id = {row.incident_id: row.classification for r in state.results.values() for row in r.old_incidents}
    assert by_id[str(unique.id)] == "unique_correct" and by_id[str(wrong.id)] == "wrong"
    assert world.session.scalars(select(SummaryBulletin)).all() == []
    assert _fresh(world, wrong).is_deleted is False and _fresh(world, wrong).decision_reason is None
    assert world.session.scalar(select(func.count()).select_from(Incident)) == 2


def test_apply_removes_wrong_row_through_audited_soft_delete(world):
    raw = _raw(world)
    unique = _row(world, raw, village="A", deaths=1)
    wrong = _row(world, raw, village="D", condition="Flare Bomb")
    _run(world, apply=True)
    wrong, unique = _fresh(world, wrong), _fresh(world, unique)
    assert unique.is_deleted is False and unique.deaths == 1
    assert wrong.is_deleted and wrong.deleted_reason == "REJECTED_WRONG_ROW" == wrong.decision_reason
    audit = world.session.scalars(select(IncidentUpdate).where(IncidentUpdate.incident_id == wrong.id)).all()
    assert any((u.new_values or {}).get("deleted_reason") == "REJECTED_WRONG_ROW" for u in audit)
    world.session.refresh(raw)
    assert raw.status == MessageStatus.summary_handled


def test_summary_row_duplicating_a_news_incident_is_rejected_as_duplicate(world):
    raw = _raw(world)
    dup = _row(world, raw, village="A")
    news = _raw(world, text="غارة على كفرا", when=POSTED - timedelta(hours=2), name="خبر")
    kept = _row(world, news, village="A")
    _run(world, apply=True)
    dup = _fresh(world, dup)
    assert dup.is_deleted and dup.decision_reason == "REJECTED_DUPLICATE" and dup.decision_ref_incident_id == kept.id
    assert _fresh(world, kept).is_deleted is False


def test_earliest_summary_row_wins_across_summaries(world):
    first = _raw(world, text=BULLETIN, when=POSTED - timedelta(hours=3), name="قناة 1")
    second = _raw(world, text=BULLETIN + "- الخيام\n", when=POSTED - timedelta(hours=1), name="قناة 2")
    early = _row(world, first, village="A")
    late = _row(world, second, village="A")
    _run(world, apply=True)
    early, late = _fresh(world, early), _fresh(world, late)
    assert early.is_deleted is False and early.decision_reason == "ACCEPTED_CONFIRMED_BY_SUMMARY"
    assert late.is_deleted and late.decision_reason == "REJECTED_DUPLICATE_SUMMARY_ROW" and late.decision_ref_incident_id == early.id


def test_rows_deleted_without_reason_get_a_reason_or_are_restored(legacy_world):
    world = legacy_world
    raw = _raw(world)
    legacy_wrong = _row(world, raw, village="D", condition="Flare Bomb", deleted=True)
    legacy_unique = _row(world, raw, village="A", deleted=True)
    _run(world, apply=True)
    legacy_wrong, legacy_unique = _fresh(world, legacy_wrong), _fresh(world, legacy_unique)
    assert legacy_wrong.is_deleted and legacy_wrong.deleted_reason == "REJECTED_WRONG_ROW"
    assert "(حُذف سابقاً بدون سبب مسجل)" in legacy_wrong.note
    assert legacy_unique.is_deleted is False and legacy_unique.decision_reason == "ACCEPTED_CONFIRMED_BY_SUMMARY"
    restored = world.session.scalars(select(IncidentUpdate).where(IncidentUpdate.incident_id == legacy_unique.id)).all()
    assert restored


def test_creates_only_for_never_arrived_and_never_writes_casualties(world):
    raw = _raw(world)
    _run(world, apply=True)
    created = world.session.scalars(select(Incident).where(Incident.origin == IncidentOrigin.summary)).all()
    assert len(created) == 2 and all(i.decision_reason == "ACCEPTED_MISSED_NEVER_ARRIVED" for i in created)
    assert all(i.deaths is None and i.total_deaths is None for i in created)


def test_failed_news_is_not_created_and_is_listed_for_reprocessing(world):
    news = _raw(world, text="غارة على كفرا", when=POSTED - timedelta(hours=1), name="خبر", status=MessageStatus.error)
    raw = _raw(world)
    state = _run(world, apply=True)
    created = world.session.scalars(select(Incident).where(Incident.origin == IncidentOrigin.summary)).all()
    assert [i.village_id for i in created] == [world.village["B"]]
    assert state.strict.failed_raw_ids[raw.id] == {news.id}


def test_second_apply_changes_nothing(legacy_world):
    world = legacy_world
    raw = _raw(world)
    _row(world, raw, village="A")
    _row(world, raw, village="D", condition="Flare Bomb")
    _row(world, raw, village="C", deleted=True)
    first = _run(world, apply=True)
    assert sum(first.changes.values()) > 0
    snapshot = world.session.execute(select(func.count()).select_from(IncidentUpdate)).scalar(), world.session.scalars(select(Incident.note).order_by(Incident.id)).all()
    second = _run(world, apply=True)
    assert sum(second.changes.values()) == 0, dict(second.changes)
    world.session.expire_all()
    assert (world.session.execute(select(func.count()).select_from(IncidentUpdate)).scalar(), world.session.scalars(select(Incident.note).order_by(Incident.id)).all()) == snapshot


def test_dry_run_decisions_equal_applied_decisions(world, tmp_path: Path):
    raw = _raw(world)
    _row(world, raw, village="A")
    _row(world, raw, village="D", condition="Flare Bomb")
    news = _raw(world, text="غارة", when=POSTED - timedelta(hours=1), name="خبر", status=MessageStatus.rejected)
    dry = _run(world, apply=False)
    paths = write_outputs(dry, apply=False, since=date(2026, 10, 1), until=date(2026, 10, 31), out_dir=tmp_path)
    world.session.rollback()
    assert world.session.scalars(select(SummaryReviewTask)).all() == []
    _run(world, apply=True)
    assert verify_against(world.session, paths["decisions"]) == 0
    assert (tmp_path / "failed_to_reprocess.csv").exists() and (tmp_path / "review_lists").is_dir()


def test_non_summary_incidents_only_receive_the_confirmation_note(world):
    news = _raw(world, text="غارة على كفرا", when=POSTED - timedelta(hours=1), name="خبر")
    untouched = _row(world, news, village="C", note="ملاحظة")
    confirmed = _row(world, news, village="A", note="ملاحظة أخرى")
    raw = _raw(world)
    before = {i.id: (i.is_deleted, i.deleted_reason, i.decision_reason, i.khabar, i.village_id, i.condition_id) for i in (untouched, confirmed)}
    _run(world, apply=True)
    for incident in (untouched, confirmed):
        fresh = _fresh(world, incident)
        assert (fresh.is_deleted, fresh.deleted_reason, fresh.decision_reason, fresh.khabar, fresh.village_id, fresh.condition_id) == before[incident.id]
    assert _fresh(world, untouched).note == "ملاحظة"
    assert _fresh(world, confirmed).note.startswith("ملاحظة أخرى") and "مؤكد في ملخص" in _fresh(world, confirmed).note


def test_classify_old_incidents_marks_duplicates_against_other_messages(world):
    raw = _raw(world)
    dup = _row(world, raw, village="A")
    other = _raw(world, text="قصف على كفرا من مصدر آخر", when=POSTED - timedelta(hours=1), name="خبر")
    _row(world, other, village="A")
    from app.news.services.summaries.condition_families import load_condition_families
    rows = classify_old_incidents(world.session, raw, [], load_condition_families(world.session))
    assert {r.incident_id: r.classification for r in rows}[str(dup.id)] == "duplicate_of_live"


def test_deleted_twin_of_an_active_row_from_the_same_summary_stays_removed(legacy_world):
    world = legacy_world
    raw = _raw(world)
    active = _row(world, raw, village="A", exact_hash="same-hash")
    twin = _row(world, raw, village="A", deleted=True, exact_hash="same-hash")
    _run(world, apply=True)
    active, twin = _fresh(world, active), _fresh(world, twin)
    assert active.is_deleted is False and active.decision_reason == "ACCEPTED_CONFIRMED_BY_SUMMARY"
    assert twin.is_deleted and twin.deleted_reason == "REJECTED_DUPLICATE_SUMMARY_ROW" and twin.decision_ref_incident_id == active.id
    assert "(حُذف سابقاً بدون سبب مسجل)" in twin.note
