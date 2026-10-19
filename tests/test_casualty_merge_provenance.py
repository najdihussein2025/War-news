"""Merge provenance guard: casualty values are adopted from a linked message only
if the evidence is in that message's cleaned body, for the same event and village.

Regression shapes from production (synthetic text, same structure):

| Incident            | Own raw | Linked raw | Path                      | Expected |
| Qantara, Oct 18     | 45002   | 45022      | story/revision merge      | null     |
| Yater, Oct 16       | 44767   | 44770      | fast-path duplicate merge | null     |
| Beit Yahoun, Oct 15 | 44527   | 44529      | fast-path duplicate merge | null     |

The linked message's only casualty "evidence" is الشهيد in the channel header.
"""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.news.models import Condition, Incident, RawMessage, Village
from app.news.models.incident_update import IncidentUpdate
from app.news.repositories import IncidentRepository
from app.news.services.incident_details.casualty_merge_provenance import (
    filter_validated_claims,
    vet_incoming_casualties,
)
from app.news.services.incident_details.incident_casualty_recompute import (
    ValidatedCasualtyClaim,
    recompute_incident_casualties,
)
from app.sources.models import Source, SourceType

# Shelling report, no casualties at all.
OWN_BODY = "قصف مدفعي إسرائيلي استهدف أطراف بلدة {village}"
# Same report re-posted under a channel header whose only casualty-like word is الشهيد.
HEADERS = (
    "صفحة الإعلامي الشهيد علي شعيب",
    "قناة الشهيد القائد للأخبار العاجلة",
    "الإعلامي الشهيد علي شعيب | أخبار الجنوب",
)
STALE_CANDIDATE = {"deaths": 1, "total_deaths": 1, "khabar": "stale extraction from header"}


def _raw(text: str, village_id: int | None = None, **extra) -> SimpleNamespace:
    match = {"village_matches": [{"matched_village_id": village_id, "village_role": "target"}]} if village_id else None
    return SimpleNamespace(id=7, raw_text=text, match_result=match, **extra)


@pytest.mark.parametrize("header", HEADERS)
def test_header_only_death_is_rejected(header):
    raw = _raw(f"{header}\n{OWN_BODY.format(village='ياطر')}")
    decision = vet_incoming_casualties(raw, STALE_CANDIDATE, incident_village_id=1)
    assert decision.values["deaths"] is None and decision.values["total_deaths"] is None
    assert {item["field"] for item in decision.rejected} == {"deaths", "total_deaths"}
    assert decision.apply_to(STALE_CANDIDATE)["deaths"] is None


def test_body_evidence_is_adopted():
    raw = _raw("غارة على ياطر أدت إلى سقوط 2 شهداء")
    decision = vet_incoming_casualties(raw, {"deaths": 2, "total_deaths": 2}, incident_village_id=1)
    assert decision.clean and decision.values["deaths"] == 2


def test_prayer_on_same_line_does_not_discard_a_real_report():
    raw = _raw("استشهاد 3 مواطنين في الغارة، رحم الله الشهداء")
    assert vet_incoming_casualties(raw, {"deaths": 3}, incident_village_id=1).clean


def test_memorial_line_does_not_count():
    raw = _raw("ذكرى استشهاد 3 من أبناء البلدة\nقصف مدفعي على ياطر")
    decision = vet_incoming_casualties(raw, {"deaths": 3}, incident_village_id=1)
    assert decision.values["deaths"] is None and decision.rejected[0]["reason"] == "header_or_memorial_evidence"


def test_other_village_and_other_event_are_rejected():
    raw = _raw("غارة أدت إلى سقوط 2 شهداء", village_id=99)
    assert vet_incoming_casualties(raw, {"deaths": 2}, incident_village_id=1).rejected[0]["reason"] == "different_village"
    raw = _raw("غارة أدت إلى سقوط 2 شهداء", village_id=1)
    assert vet_incoming_casualties(raw, {"deaths": 2}, incident_village_id=1, same_event=False).rejected[0]["reason"] == "different_event"


def test_recompute_claims_on_header_lines_are_filtered():
    body = "قناة الشهيد القائد\nقصف مدفعي على ياطر"
    claim = ValidatedCasualtyClaim(5, "raw_messages", 1, "Yater", {"deaths": 1}, {"deaths": "قناة الشهيد القائد"})
    kept, rejected = filter_validated_claims([claim], {5: body})
    assert kept == [] and rejected[0]["reason"] == "header_or_memorial_evidence"
    body_ok = "قصف مدفعي على ياطر أدى إلى استشهاد 2"
    claim_ok = ValidatedCasualtyClaim(5, "raw_messages", 1, "Yater", {"deaths": 2}, {"deaths": "استشهاد 2"})
    assert filter_validated_claims([claim_ok], {5: body_ok})[0] == [claim_ok]


# --- database regression tests (rolled back; need a *_test database) -------------------

@pytest.fixture
def db():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for repository integration coverage.")
    engine = create_engine(database_url)
    try:
        connection = engine.connect()
    except OperationalError as exc:
        pytest.skip(f"Database is unavailable: {exc}")
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _world(db: Session, village_name: str, own_text: str, linked_text: str, *, linked_later: bool = True):
    marker = uuid4().hex
    source = Source(type=SourceType.api, name=f"Provenance source {marker}", config={})
    village = Village(acs_code=int(marker[:7], 16), ref_name_en=f"Prov {marker}", ref_name_ar=village_name)
    condition = Condition(action_en=f"Condition {marker}", action_ar=f"حالة {marker}")
    db.add_all([source, village, condition])
    db.flush()
    now = datetime(2026, 10, 18, 7, 8, tzinfo=timezone.utc)
    target = {"village_matches": [{"matched_village_id": village.id, "village_role": "target"}]}
    own = RawMessage(source_id=source.id, external_message_id=f"{marker}-own", raw_text=own_text, raw_payload={},
                     match_result=target, message_datetime=now, received_at=now)
    later = now + timedelta(minutes=14 if linked_later else -14)
    linked = RawMessage(source_id=source.id, external_message_id=f"{marker}-linked", raw_text=linked_text,
                        raw_payload={}, match_result=target, message_datetime=later, received_at=later)
    db.add_all([own, linked])
    db.flush()
    incident = Incident(raw_message_id=own.id, village_id=village.id, condition_id=condition.id, source_id=source.id,
                        event_date=date(2026, 10, 18), event_time=time(7, 8), khabar=own_text,
                        verification_status="auto_processed")
    db.add(incident)
    db.flush()
    return incident, own, linked


@pytest.mark.parametrize("village,header", [("القنطرة", HEADERS[0]), ("ياطر", HEADERS[1]), ("بيت ياحون", HEADERS[2])])
def test_fast_path_duplicate_merge_does_not_adopt_header_death(db, village, header):
    """Yater 44767/44770 and Beit Yahoun 44527/44529: fast-path duplicate merge."""
    own_text = OWN_BODY.format(village=village)
    incident, own, linked = _world(db, village, own_text, f"{header}\n{own_text}")
    repo = IncidentRepository(db)
    repo.create_fast_path_duplicate_match(canonical_incident=incident, raw_message_id=linked.id)

    repo.merge_existing(incident, dict(STALE_CANDIDATE), linked.id)

    assert (incident.deaths, incident.total_deaths, incident.injuries, incident.total_injuries) == (None,) * 4
    update = db.scalars(select(IncidentUpdate).where(IncidentUpdate.incident_id == incident.id)).all()[-1]
    rejected = update.new_values["casualty_provenance_rejected"]
    assert {item["field"] for item in rejected} == {"deaths", "total_deaths"}
    # A header the vocabulary already strips leaves no evidence at all; any other
    # header is caught on its line. Either way nothing is adopted.
    assert {item["reason"] for item in rejected} <= {"header_or_memorial_evidence", "evidence_not_in_cleaned_body"}


def test_story_revision_merge_does_not_adopt_header_death(db):
    """Qantara 45002/45022: story/revision merge of a later header-only repost."""
    own_text = OWN_BODY.format(village="القنطرة")
    incident, own, linked = _world(db, "القنطرة", own_text, f"{HEADERS[0]}\n{own_text}")
    repo = IncidentRepository(db)
    repo.create_fast_path_duplicate_match(canonical_incident=incident, raw_message_id=linked.id)

    repo.apply_story_revision(incident, dict(STALE_CANDIDATE), linked.id)

    assert (incident.deaths, incident.total_deaths) == (None, None)
    update = db.scalars(select(IncidentUpdate).where(IncidentUpdate.incident_id == incident.id)).all()[-1]
    assert update.new_values["casualty_provenance_rejected"]


def test_recompute_ignores_header_only_linked_message(db):
    own_text = OWN_BODY.format(village="ياطر")
    incident, own, linked = _world(db, "ياطر", own_text, f"{HEADERS[2]}\n{own_text}")
    IncidentRepository(db).create_fast_path_duplicate_match(canonical_incident=incident, raw_message_id=linked.id)
    incident.deaths = incident.total_deaths = 1  # value a stale merge wrote earlier

    recompute_incident_casualties(db, incident, reason_code="repair")

    assert (incident.deaths, incident.total_deaths) == (None, None)


def test_recompute_ignores_indefinite_noun_in_channel_header(db):
    """A header such as «قناة شهيد الجنوب» does read as one death to the mention parser."""
    own_text = OWN_BODY.format(village="ياطر")
    incident, own, linked = _world(db, "ياطر", own_text, f"قناة شهيد الجنوب\n{own_text}")
    IncidentRepository(db).create_fast_path_duplicate_match(canonical_incident=incident, raw_message_id=linked.id)

    recompute_incident_casualties(db, incident, reason_code="repair")

    assert (incident.deaths, incident.total_deaths) == (None, None)
    update = db.scalars(select(IncidentUpdate).where(IncidentUpdate.incident_id == incident.id)).all()
    assert not update or "casualty_provenance_rejected" in update[-1].new_values or update[-1].new_values.get("deaths") is None


def test_genuine_body_casualties_still_merge(db):
    own_text = OWN_BODY.format(village="ياطر")
    incident, own, linked = _world(db, "ياطر", own_text, f"{own_text}، وأدى القصف إلى سقوط 2 شهداء و3 جرحى")
    repo = IncidentRepository(db)
    repo.create_fast_path_duplicate_match(canonical_incident=incident, raw_message_id=linked.id)

    repo.merge_existing(incident, {"deaths": 2, "total_deaths": 2, "injuries": 3, "total_injuries": 3, "khabar": "k"}, linked.id)

    assert (incident.deaths, incident.injuries) == (2, 3)
