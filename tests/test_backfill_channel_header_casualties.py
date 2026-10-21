"""Backfill: clear header-only casualties, keep real ones, skip admin-edited rows."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

import app.news.services  # noqa: F401  (import order: loader <-> matching_service)
from app.accounts.models import Role, User
from app.news.models import Incident, IncidentDetail, IncidentUpdate, UpdateAction
from app.news.models.raw_message import RawMessage
from scripts.backfill_channel_header_casualties import (
    apply_plan,
    collect_plans,
    summarize,
    write_csv,
)
from tests.test_casualty_merge_provenance import OWN_BODY, _world, db  # noqa: F401

HEADER = "صفحة الإعلامي الشهيد علي شعيب"
BODY_DEATH = "استشهاد مواطن بغارة على بلدة كفرا"


def _plan_for(db, incident):
    return next(p for p in collect_plans(db) if p.incident_id == incident.id)


def test_header_only_death_is_cleared_with_status_and_details(db):  # noqa: F811
    own = OWN_BODY.format(village="ياطر")
    incident, own_raw, linked = _world(db, "ياطر", own, f"{HEADER}\n{own}")
    own_raw.raw_text = f"{HEADER}\n{own}"  # raw 44770 shape: the canonical itself carries the header
    incident.deaths = incident.total_deaths = 1
    incident.casualty_status = "exact"
    incident.casualty_deaths_status = "exact"
    incident.casualty_status_evidence = "شهيد"
    db.add(IncidentDetail(incident_id=incident.id, male_d=1))
    db.flush()

    plan = _plan_for(db, incident)

    cleared = {c.field: c for c in plan.cleared}
    assert set(cleared) == {"deaths", "total_deaths", "detail.male_d"}
    assert {c.reason for c in cleared.values()} == {"header_only"}
    assert all(c.new is None for c in cleared.values())
    statuses = {c.field: c.new for c in plan.status_fixed}
    assert statuses["casualty_status"] == "none_mentioned"
    assert statuses["casualty_status_evidence"] is None
    assert not plan.kept


def test_real_body_death_is_kept(db):  # noqa: F811
    own = f"{HEADER}\n{BODY_DEATH}"
    incident, own_raw, _linked = _world(db, "كفرا", own, own)
    incident.deaths = incident.total_deaths = 1
    incident.casualty_status = "exact"
    db.flush()

    plan = _plan_for(db, incident)

    assert not plan.cleared
    assert set(plan.kept) == {"deaths=1", "total_deaths=1"}


def test_death_grounded_in_a_merged_message_is_kept(db):  # noqa: F811
    own = OWN_BODY.format(village="كفرا")
    incident, _own_raw, linked = _world(db, "كفرا", own, f"{HEADER}\n{BODY_DEATH}")
    incident.deaths = incident.total_deaths = 1
    incident.casualty_status = "exact"
    db.add(IncidentUpdate(
        incident_id=incident.id, action=UpdateAction.pipeline_merge, old_values={},
        new_values={"merged_from": {"raw_message_id": linked.id, "channel": None, "khabar": linked.raw_text}},
    ))
    db.flush()

    plan = _plan_for(db, incident)

    assert not plan.cleared and "deaths=1" in plan.kept


def test_status_is_fixed_when_numbers_contradict_it(db):  # noqa: F811
    own = f"{HEADER}\n{BODY_DEATH}"
    incident, _o, _l = _world(db, "كفرا", own, own)
    incident.deaths = incident.total_deaths = 1
    incident.casualty_status = "none_mentioned"
    db.flush()

    plan = _plan_for(db, incident)

    assert {c.field: c.new for c in plan.status_fixed}["casualty_status"] == "exact"


def test_admin_edited_and_verified_rows_are_skipped(db):  # noqa: F811
    own = OWN_BODY.format(village="ياطر")
    edited, edited_raw, _l = _world(db, "ياطر", own, own)
    edited_raw.raw_text = f"{HEADER}\n{own}"
    edited.deaths = edited.total_deaths = 1
    role = db.scalar(select(Role).limit(1))
    admin = User(username=f"u{uuid4().hex[:8]}", password_hash="x", full_name="Admin", role_id=role.id)
    db.add(admin)
    db.flush()
    db.add(IncidentUpdate(incident_id=edited.id, action=UpdateAction.edit, old_values={},
                          new_values={"deaths": 1}, performed_by=admin.id))
    verified, verified_raw, _l2 = _world(db, "ياطر", own, own)
    verified_raw.raw_text = f"{HEADER}\n{own}"
    verified.deaths = verified.total_deaths = 1
    verified.verified_by_user_id = admin.id
    db.flush()

    plans = {p.incident_id: p for p in collect_plans(db)}

    assert plans[edited.id].skipped == "admin_edited" and not plans[edited.id].changes
    assert plans[verified.id].skipped == "verified" and not plans[verified.id].changes
    counts = summarize(list(plans.values()))
    assert counts["skipped_admin_edited"] >= 1 and counts["skipped_verified"] >= 1


def test_dry_run_changes_nothing_and_csv_lists_rows(db, tmp_path):  # noqa: F811
    own = OWN_BODY.format(village="ياطر")
    incident, own_raw, _l = _world(db, "ياطر", own, own)
    own_raw.raw_text = f"{HEADER}\n{own}"
    incident.deaths = incident.total_deaths = 1
    incident.casualty_status = "exact"
    db.flush()

    plans = collect_plans(db)
    path = write_csv(plans, tmp_path / "out.csv")

    assert incident.deaths == 1  # planning never mutates
    text = path.read_text(encoding="utf-8-sig")
    assert "incident_id,village,date,field,old -> new,reason,linked_raw_ids" in text
    assert "1 -> None,header_only" in text


def test_apply_writes_nulls_and_an_audit_row(db):  # noqa: F811
    own = OWN_BODY.format(village="ياطر")
    incident, own_raw, _l = _world(db, "ياطر", own, own)
    own_raw.raw_text = f"{HEADER}\n{own}"
    incident.deaths = incident.total_deaths = 1
    incident.casualty_status = "exact"
    db.flush()

    apply_plan(db, _plan_for(db, incident))
    db.flush()
    db.refresh(incident)

    assert (incident.deaths, incident.total_deaths) == (None, None)
    assert incident.casualty_status == "none_mentioned"
    audit = db.scalars(select(IncidentUpdate).where(IncidentUpdate.incident_id == incident.id)).all()[-1]
    assert audit.new_values["channel_header_casualty_cleanup"] is True and audit.performed_by is None


def test_real_casualty_with_stored_body_evidence_is_kept_and_breakdown_follows(db):  # noqa: F811
    """«استشهد الشاب …» has no count word; the stored extraction evidence in the body grounds it."""
    body = "استشهد الشاب محمد دايخ صباحا بغارة مسيرة على النبطية"
    incident, own_raw, _l = _world(db, "النبطية", body, body)
    own_raw.extraction_result = {
        "casualties": {"deaths": 1},
        "casualty_evidence": [{"field": "deaths", "evidence_span": "استشهد الشاب محمد دايخ"}],
    }
    incident.deaths = incident.total_deaths = 1
    incident.casualty_status = "exact"
    db.add(IncidentDetail(incident_id=incident.id, male_d=1))
    db.flush()

    plan = _plan_for(db, incident)

    assert not plan.cleared
    assert "deaths=1" in plan.kept


def test_gender_breakdown_is_not_cleared_while_the_main_count_is_grounded(db):  # noqa: F811
    body = "وشهيدان في اعتداء إسرائيلي مزدوج على بلدة عربصاليم"
    incident, _o, _l = _world(db, "عربصاليم", body, body)
    incident.deaths = incident.total_deaths = 2
    incident.casualty_status = "exact"
    db.add(IncidentDetail(incident_id=incident.id, male_d=2))
    db.flush()

    plan = _plan_for(db, incident)

    assert not plan.cleared and "detail.male_d=2" in plan.kept


def test_header_evidence_span_in_stored_extraction_does_not_ground(db):  # noqa: F811
    own = OWN_BODY.format(village="ياطر")
    incident, own_raw, _l = _world(db, "ياطر", own, own)
    own_raw.raw_text = f"{HEADER}\n{own}"
    own_raw.extraction_result = {
        "casualties": {"deaths": 1},
        "casualty_evidence": [{"field": "deaths", "evidence_span": "شهيد"}],
    }
    incident.deaths = incident.total_deaths = 1
    db.flush()

    assert {c.field for c in _plan_for(db, incident).cleared} == {"deaths", "total_deaths"}
