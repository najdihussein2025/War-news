"""Status consistency, Unclassified -> Needs verification, shared-toll flags, people KPI."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

import app.news.services  # noqa: F401  (import order: loader <-> matching_service)
from app.llm.dtos import CasualtyScope, ExtractionCasualties, ExtractionResult
from app.news.models import Condition, Incident
from app.news.repositories import IncidentRepository
from app.news.repositories.bulletin_casualty_group_repository import BulletinCasualtyGroupRepository
from app.news.repositories.reported_casualties import (
    has_reported_casualties_expression,
    reported_casualty_people_expression,
)
from app.news.services.incident_details.casualty_status import enforce_status_matches_numbers
from app.news.services.materialization.verification_signals import (
    SHARED_TOLL_DISTRIBUTE_REASON,
    UNCLASSIFIED_ACTION_AR,
    UNCLASSIFIED_REVIEW_REASON,
    VerificationSignals,
    _verification_reason,
    apply_unclassified_review,
    decide_verification,
    is_unclassified_condition,
)
from tests.test_casualty_merge_provenance import OWN_BODY, _world, db  # noqa: F401
from tests.test_incident_materialization_service import _SessionStub
from tests.test_shared_toll_owner import (
    SHARED_TEXT,
    _fast_dedup,
    _match,
    _owned_group,
    _representative,
    _roles,
)
from app.news.services.materialization.incident_materialization_service import (
    IncidentMaterializationService,
)

HEADER = "صفحة الإعلامي الشهيد علي شعيب"


def _row(**values):
    base = dict(
        deaths=None, injuries=None, total_deaths=None, total_injuries=None,
        casualty_status=None, casualty_deaths_status=None, casualty_injuries_status=None,
        casualty_status_evidence=None,
    )
    return SimpleNamespace(**{**base, **values})


# --- status consistency ----------------------------------------------------------


def test_number_above_zero_is_never_none_mentioned():
    row = _row(deaths=1, total_deaths=1, casualty_status="none_mentioned",
               casualty_deaths_status="none_mentioned", casualty_injuries_status="none_mentioned")
    assert enforce_status_matches_numbers(row)
    assert (row.casualty_status, row.casualty_deaths_status) == ("exact", "exact")
    assert row.casualty_injuries_status == "none_mentioned"


def test_all_null_is_never_exact_and_loses_its_evidence():
    row = _row(casualty_status="exact", casualty_deaths_status="exact", casualty_status_evidence="شهيد")
    assert enforce_status_matches_numbers(row)
    assert row.casualty_status == "none_mentioned"
    assert row.casualty_deaths_status == "none_mentioned"
    assert row.casualty_status_evidence is None


@pytest.mark.parametrize("status", ["count_missing", "aggregate_only", "explicit_none"])
def test_wording_statuses_are_left_alone(status):
    row = _row(casualty_status=status)
    assert not enforce_status_matches_numbers(row)
    assert row.casualty_status == status


def test_status_agrees_with_numbers_after_a_pipeline_merge(db):  # noqa: F811
    own = OWN_BODY.format(village="كفرا")
    incident, _own, linked = _world(db, "كفرا", own, f"{HEADER}\nاستشهاد مواطن بغارة على بلدة كفرا")
    incident.casualty_status = "none_mentioned"
    repo = IncidentRepository(db)
    repo.create_fast_path_duplicate_match(canonical_incident=incident, raw_message_id=linked.id)
    repo.merge_existing(incident, {"deaths": 1, "total_deaths": 1, "khabar": "x"}, linked.id)
    assert incident.deaths == 1 and incident.casualty_status == "exact"


def test_status_agrees_with_numbers_when_a_header_death_is_refused(db):  # noqa: F811
    own = OWN_BODY.format(village="ياطر")
    incident, _own, linked = _world(db, "ياطر", own, f"{HEADER}\n{own}")
    incident.casualty_status = "exact"  # what a stale merge left behind
    repo = IncidentRepository(db)
    repo.create_fast_path_duplicate_match(canonical_incident=incident, raw_message_id=linked.id)
    repo.merge_existing(incident, {"deaths": 1, "total_deaths": 1, "khabar": "x"}, linked.id)
    assert incident.deaths is None and incident.casualty_status == "none_mentioned"


# --- Unclassified -> Needs verification ---------------------------------------------


def test_decide_verification_flags_unclassified_with_its_reason():
    status, reasons, _flags, payload = decide_verification(None, VerificationSignals(unclassified_action=True))
    assert status == "needs_verification"
    assert reasons == [UNCLASSIFIED_REVIEW_REASON]
    assert payload["review"]["rule"] == "classification"
    assert decide_verification(None, VerificationSignals())[0] == "auto_processed"


def test_verification_reason_helper_adds_the_unclassified_reason():
    assert _verification_reason({}, unclassified_action=True) == UNCLASSIFIED_REVIEW_REASON
    assert _verification_reason({}) is None


class _ConditionLookupSession(_SessionStub):
    """Answers the condition lookup with the Unclassified action; otherwise the stub."""

    def get(self, model, ident):
        return SimpleNamespace(id=ident, action_ar=UNCLASSIFIED_ACTION_AR)


def test_fast_path_flags_an_unclassified_action():
    extraction = ExtractionResult(
        is_relevant=True, village=["صور"], village_roles=_roles("صور"), casualty_scope=CasualtyScope.unspecified,
        model="test", extracted_at=datetime.now(timezone.utc),
    )
    rep = _representative("قصف على صور", extraction, [_match("صور", 201)])
    service = IncidentMaterializationService(
        _ConditionLookupSession(),  # type: ignore[arg-type]
        bulletin_groups=SimpleNamespace(
            create_for_message=lambda **_k: SimpleNamespace(owner_village_id=None),
            get_by_raw_message_id=lambda *_a, **_k: None,
        ),
    )
    created = service.process_fast_path(rep, _fast_dedup())  # type: ignore[arg-type]
    assert [i.verification_status for i in created] == ["needs_verification"]
    assert created[0].verification_reason == UNCLASSIFIED_REVIEW_REASON


def test_merge_path_flags_an_unclassified_action(db):  # noqa: F811
    own = OWN_BODY.format(village="كفرا")
    incident, _own, linked = _world(db, "كفرا", own, own)
    assert not is_unclassified_condition(db, incident.condition_id)
    unclassified_id = db.scalar(select(Condition.id).where(Condition.action_ar == UNCLASSIFIED_ACTION_AR))
    if unclassified_id is None:  # not seeded in this database: create it
        unclassified = Condition(action_en="Unclassified / Needs Review", action_ar=UNCLASSIFIED_ACTION_AR)
        db.add(unclassified)
        db.flush()
        unclassified_id = unclassified.id
    incident.condition_id = unclassified_id
    db.flush()
    repo = IncidentRepository(db)
    repo.create_fast_path_duplicate_match(canonical_incident=incident, raw_message_id=linked.id)
    repo.merge_existing(incident, {"khabar": "x"}, linked.id)
    assert incident.verification_status == "needs_verification"
    assert UNCLASSIFIED_REVIEW_REASON in incident.verification_reason
    # a human decision is never overridden
    incident.verification_status, incident.verification_reason = "verified", None
    assert not apply_unclassified_review(db, incident)
    assert incident.verification_status == "verified"


# --- shared toll ------------------------------------------------------------------


def test_shared_toll_across_three_villages_flags_every_row(db):  # noqa: F811
    raw, group, incidents = _owned_group(db)
    incidents[0].total_deaths = incidents[0].deaths = 10  # total on the owner only
    changed = BulletinCasualtyGroupRepository(db).flag_for_distribution(group)
    assert changed == 3
    for incident in incidents:
        db.refresh(incident)
        assert incident.verification_status == "needs_verification"
        assert incident.verification_reason == SHARED_TOLL_DISTRIBUTE_REASON
    assert [i.total_deaths for i in incidents] == [10, None, None]
    # idempotent, and a verified row is left alone
    incidents[1].verification_status = "verified"
    assert BulletinCasualtyGroupRepository(db).flag_for_distribution(group) == 0
    assert incidents[1].verification_status == "verified"


def test_fast_path_shared_toll_flags_all_rows():
    extraction = ExtractionResult(
        is_relevant=True, village=["صور", "النبطية", "بيروت"], village_roles=_roles("صور", "النبطية", "بيروت"),
        casualty_scope=CasualtyScope.bulletin_aggregate, casualty_scope_evidence=SHARED_TEXT,
        casualties=ExtractionCasualties(total_deaths=10),
        model="test", extracted_at=datetime.now(timezone.utc),
    )
    rep = _representative(SHARED_TEXT, extraction,
                          [_match("صور", 201), _match("النبطية", 202), _match("بيروت", 203)])
    service = IncidentMaterializationService(
        _SessionStub(),  # type: ignore[arg-type]
        bulletin_groups=SimpleNamespace(
            create_for_message=lambda **_k: SimpleNamespace(owner_village_id=None),
            get_by_raw_message_id=lambda *_a, **_k: None,
        ),
    )
    created = service.process_fast_path(rep, _fast_dedup())  # type: ignore[arg-type]
    assert len(created) == 3
    assert {i.verification_status for i in created} == {"needs_verification"}


# --- KPI ---------------------------------------------------------------------------


def test_kpi_sums_people_not_incidents(db):  # noqa: F811
    own = OWN_BODY.format(village="كفرا")
    first, _o, _l = _world(db, "كفرا", own, own)
    ids = [first.id]
    for deaths, injuries in ((2, 3), (None, 4), (None, None)):
        row = Incident(
            raw_message_id=first.raw_message_id, village_id=first.village_id, condition_id=first.condition_id,
            source_id=first.source_id, event_date=first.event_date, khabar=f"k{len(ids)}",
            total_deaths=deaths, total_injuries=injuries, verification_status="auto_processed",
        )
        db.add(row)
        db.flush()
        ids.append(row.id)
    people = db.scalar(
        select(func.coalesce(func.sum(reported_casualty_people_expression()).filter(has_reported_casualties_expression()), 0))
        .where(Incident.id.in_(ids))
    )
    incidents_with_casualties = db.scalar(
        select(func.count(Incident.id)).filter(has_reported_casualties_expression()).where(Incident.id.in_(ids))
    )
    assert people == 9 and incidents_with_casualties == 2  # 2+3 and 4 people over 2 incidents
