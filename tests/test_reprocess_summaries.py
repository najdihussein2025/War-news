"""Backfill script: dry run writes nothing; --apply classifies and fixes old-path incidents."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.news.models import Condition, Incident, IncidentOrigin, MessageStatus, RawMessage
from app.news.models.summary_bulletin import SummaryBulletin
from app.news.services.summaries.condition_families import load_condition_families
from scripts.reprocess_summaries import (
    classify_old_incidents,
    process_message,
    select_candidate_messages,
)
from tests.summary_db import build_world

BULLETIN = (
    "ملخص الاعتداءات\n"
    "الغارات:\n"
    "- كفرا\n"
    "- صديقين\n"
)


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


def _summary_raw_message(world, *, text=BULLETIN, hours_ago=1) -> RawMessage:
    when = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    raw = RawMessage(
        source_id=world.source_id, raw_text=text, raw_payload={}, status=MessageStatus.materialized,
        external_message_id=f"backfill-{when.timestamp()}", source_name="قناة اختبار", message_datetime=when,
    )
    world.session.add(raw)
    world.session.flush()
    return raw


def _old_incident(world, raw, *, village="A", condition="Bombs", deaths=None) -> Incident:
    incident = Incident(
        raw_message_id=raw.id, village_id=world.village[village], condition_id=world.condition[condition],
        event_date=(raw.message_datetime or datetime.now(timezone.utc)).date(),
        khabar="خبر قديم", source_id=world.source_id, origin=IncidentOrigin.live, deaths=deaths,
    )
    world.session.add(incident)
    world.session.flush()
    return incident


def test_select_candidate_messages_excludes_already_processed(world):
    raw = _summary_raw_message(world)
    other = _summary_raw_message(world, text="خبر عادي بدون ملخص")
    already = _summary_raw_message(world)
    world.session.add(SummaryBulletin(
        raw_message_id=already.id, fingerprint="x", status="failed", parser_version="t",
    ))
    world.session.flush()
    ids = select_candidate_messages(world.session, date.today() - timedelta(days=1), date.today() + timedelta(days=1), None)
    assert raw.id in ids and other.id in ids and already.id not in ids


def test_non_summary_message_is_skipped_and_not_classified(world):
    raw = _summary_raw_message(world, text="خبر عادي: قصف على كفرا")
    families = load_condition_families(world.session)
    result = process_message(world.session, raw.id, apply=False, families=families)
    assert result is None
    assert world.session.scalars(select(SummaryBulletin)).all() == []


def test_dry_run_classifies_but_writes_nothing(world):
    raw = _summary_raw_message(world)
    unique = _old_incident(world, raw, village="A")
    wrong = _old_incident(world, raw, village="D", condition="Flare Bomb")
    families = load_condition_families(world.session)

    result = process_message(world.session, raw.id, apply=False, families=families)

    assert result is not None and result.applied is False
    by_id = {row.incident_id: row.classification for row in result.old_incidents}
    assert by_id[str(unique.id)] == "unique_correct"
    assert by_id[str(wrong.id)] == "wrong"
    # nothing persisted
    assert world.session.scalars(select(SummaryBulletin)).all() == []
    assert world.session.get(Incident, unique.id).is_deleted is False


def test_duplicate_of_live_is_detected_against_a_different_message(world):
    raw = _summary_raw_message(world)
    dup = _old_incident(world, raw, village="A")
    other_raw = _summary_raw_message(world, text="قصف على كفرا من مصدر آخر")
    dup_elsewhere = _old_incident(world, other_raw, village="A")  # same village+condition+day, different message
    families = load_condition_families(world.session)
    result = process_message(world.session, raw.id, apply=False, families=families)
    by_id = {row.incident_id: row.classification for row in result.old_incidents}
    assert by_id[str(dup.id)] == "duplicate_of_live"


def test_apply_is_idempotent_links_unique_correct_and_removes_wrong(world):
    raw = _summary_raw_message(world)
    unique = _old_incident(world, raw, village="A", deaths=1)
    wrong = _old_incident(world, raw, village="D", condition="Flare Bomb")
    families = load_condition_families(world.session)

    first = process_message(world.session, raw.id, apply=True, families=families)
    world.session.commit()
    assert first is not None and first.applied

    world.session.refresh(unique)
    world.session.refresh(wrong)
    world.session.refresh(raw)
    assert unique.is_deleted is False and unique.deaths == 1  # kept, untouched
    assert wrong.is_deleted is True and wrong.deleted_reason == "summary_superseded"
    assert "Superseded by summary" in (wrong.note or "")
    assert raw.status == MessageStatus.summary_handled

    incidents = world.session.scalars(select(Incident).where(Incident.raw_message_id == raw.id, Incident.is_deleted.is_(False))).all()
    assert incidents == [unique]  # the "B" item had no old-path incident, so reconciliation created its own
    created_for_b = world.session.scalars(select(Incident).where(Incident.village_id == world.village["B"])).all()
    assert created_for_b and created_for_b[0].origin == IncidentOrigin.summary

    # second pass over the same raw message is a no-op: already has a SummaryBulletin row
    families2 = load_condition_families(world.session)
    second = process_message(world.session, raw.id, apply=True, families=families2)
    world.session.commit()
    assert second is None


def test_apply_never_touches_incidents_from_other_raw_messages(world):
    raw = _summary_raw_message(world)
    _old_incident(world, raw, village="D", condition="Flare Bomb")  # "wrong" -> removed
    other_raw = _summary_raw_message(world, text="خبر منفصل بدون ملخص")
    untouched = _old_incident(world, other_raw, village="C")
    families = load_condition_families(world.session)
    process_message(world.session, raw.id, apply=True, families=families)
    world.session.commit()
    world.session.refresh(untouched)
    assert untouched.is_deleted is False and untouched.deleted_reason is None
