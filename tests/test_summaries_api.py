"""Summaries API + review service (scratch DB) and the admin-only guard."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.accounts.models import RoleName
from app.api import summaries_router
from app.api.deps import require_admin
from app.news.models import Incident, IncidentOrigin, VillageLocationAlias
from app.news.models.summary_bulletin import (
    SummaryHeaderMapping,
    SummaryItem,
    SummaryReconciliationStatus,
    SummaryResolution,
    SummaryReviewStatus,
    SummaryReviewTask,
    SummaryStatus,
)
from app.news.repositories.incident_repository import IncidentRepository
from app.news.dtos import IncidentListParams
from app.news.services.summaries.review_service import (
    ResolveRequest,
    ReviewAction,
    ReviewError,
    dismiss_review_task,
    list_summaries,
    resolve_review_task,
    summary_detail,
)
from tests.summary_db import add_incident, add_summary, at, build_world

TEXT = "الاعتداءات الجديدة:\n- كفرا\n- صديقين"


@pytest.fixture
def world():
    w = build_world()
    yield w
    w.session.rollback()
    w.session.close()


def _row(world, summary, **kwargs) -> SummaryItem:
    item = SummaryItem(
        summary_id=summary.id, position=kwargs.pop("position", 90), location_text=kwargs.pop("location", "مكان"),
        evidence_span=kwargs.pop("evidence", "مكان"), **kwargs,
    )
    world.session.add(item)
    world.session.flush()
    return item


def _task(world, summary, reasons) -> SummaryReviewTask:
    task = SummaryReviewTask(summary_id=summary.id, reasons=reasons, status=SummaryReviewStatus.open)
    world.session.add(task)
    summary.status = SummaryStatus.needs_review
    world.session.flush()
    return task


def _unresolved_place_summary(world):
    summary = add_summary(world, [{"village": "A"}])
    row = _row(world, summary, location="قرية جديدة", header_text="الغارات", condition_id=world.condition["Bombs"],
               resolution=SummaryResolution.unresolved_location)
    task = _task(world, summary, [{"type": "unresolved_location", "item_ids": [row.id], "text": "قرية جديدة"}])
    return summary, row, task


# ---- guard ---------------------------------------------------------------------------------

def test_every_summaries_route_requires_admin_or_super_admin():
    routes = [r for r in summaries_router.router.routes if hasattr(r, "dependant")]
    assert len(routes) == 4
    for route in routes:
        assert any(dep.call is require_admin for dep in route.dependant.dependencies), route.path


@pytest.mark.parametrize("role", [RoleName.admin, RoleName.super_admin])
def test_admin_roles_pass_the_guard(role):
    user = SimpleNamespace(role=SimpleNamespace(name=role))
    assert require_admin(current_user=user) is user


def test_unauthenticated_request_is_rejected_before_any_role_check():
    from app.api.deps import get_current_user

    request = SimpleNamespace(cookies={})
    with pytest.raises(HTTPException) as caught:
        get_current_user(request=request, credentials=None, db=None)
    assert caught.value.status_code == 401
    assert set(RoleName) == {RoleName.admin, RoleName.super_admin}, "a new role needs a deliberate decision here"


# ---- list / detail -----------------------------------------------------------------------------

def test_list_defaults_hide_fully_matched_summaries_and_filters_work(world):
    shown = add_summary(world, [{"village": "A"}], channel="قناة أ")
    hidden = add_summary(world, [{"village": "B"}], channel="قناة ب")
    hidden.hidden = True
    _, row, task = _unresolved_place_summary(world)
    world.session.flush()

    rows, total = list_summaries(world.session)
    ids = {r["id"] for r in rows}
    assert shown.id in ids and hidden.id not in ids and total == 2

    rows, _ = list_summaries(world.session, include_hidden=True)
    assert hidden.id in {r["id"] for r in rows}
    rows, _ = list_summaries(world.session, channel="قناة أ")
    assert [r["id"] for r in rows] == [shown.id]
    rows, _ = list_summaries(world.session, has_open_task=True)
    assert len(rows) == 1 and rows[0]["has_open_task"] and rows[0]["unresolved_count"] == 1
    assert rows[0]["reasons"] == [{"type": "unresolved_location", "count": 1}]
    rows, _ = list_summaries(world.session, status="needs_review")
    assert len(rows) == 1
    rows, _ = list_summaries(world.session, date_from=date(2026, 10, 8), date_to=date(2026, 10, 8))
    assert len(rows) == 2  # window ends 2026-10-08 00:00 local; the hidden one is excluded
    rows, _ = list_summaries(world.session, date_from=date(2026, 10, 9))
    assert rows == []
    with pytest.raises(ReviewError):
        list_summaries(world.session, status="nope")


def test_list_paginates_and_excludes_reposts(world):
    first = add_summary(world, [{"village": "A"}])
    repost = add_summary(world, [{"village": "A"}], channel="ثانية", status=SummaryStatus.skipped_repost)
    repost.canonical_summary_id = first.id
    for _ in range(3):
        add_summary(world, [{"village": "B"}])
    world.session.flush()
    rows, total = list_summaries(world.session, page=1, page_size=2)
    assert total == 4 and len(rows) == 2
    rows2, _ = list_summaries(world.session, page=2, page_size=2)
    assert not {r["id"] for r in rows} & {r["id"] for r in rows2}
    assert repost.id not in {r["id"] for r in rows + rows2}


def test_detail_has_text_window_items_reposts_and_task(world):
    summary, row, task = _unresolved_place_summary(world)
    summary.window_basis = "default"
    repost = add_summary(world, [{"village": "A"}], channel="قناة مكررة", status=SummaryStatus.skipped_repost)
    repost.canonical_summary_id = summary.id
    world.session.flush()
    detail = summary_detail(world.session, summary.id)
    assert detail["raw_text"] == "ملخص" and detail["window_start"] and detail["window_end"]
    assert [r["channel"] for r in detail["reposts"]] == ["قناة مكررة"]
    statuses = {i["id"]: i["display_status"] for i in detail["items"]}
    assert statuses[row.id] == "unresolved" and "pending" in statuses.values()
    first = detail["items"][0]
    assert first["primary_village"]["name_ar"] == "كفرا" and first["condition"]["name_en"] == "Bombs"
    assert detail["review_task"]["status"] == "open" and detail["review_task"]["reasons"][0]["type"] == "unresolved_location"
    assert summary_detail(world.session, 999999) is None


# ---- resolve -----------------------------------------------------------------------------------

def test_resolve_location_updates_item_saves_alias_and_queues_summary(world):
    summary, row, task = _unresolved_place_summary(world)
    user = None
    out = resolve_review_task(
        world.session, summary.id,
        ResolveRequest(actions=[ReviewAction(item_id=row.id, village_id=world.village["B"], save_alias=True)]), user,
    )
    assert out.handled_item_ids == [row.id] and out.task_status == "resolved" and out.alias_saved == [row.id]
    assert (row.resolution, row.reconciliation_status) == (SummaryResolution.resolved, SummaryReconciliationStatus.pending)
    assert row.primary_village_id == world.village["B"]
    alias = world.session.scalar(select(VillageLocationAlias).where(VillageLocationAlias.alias_text == "قرية جديدة"))
    assert alias is not None and alias.village_id == world.village["B"]
    assert task.status == SummaryReviewStatus.resolved and task.resolved_at is not None
    assert summary.status == SummaryStatus.parsed and summary.process_after is not None


def test_resolve_location_without_alias_saves_none_and_needs_a_valid_village(world):
    summary, row, _ = _unresolved_place_summary(world)
    with pytest.raises(ReviewError):
        resolve_review_task(world.session, summary.id, ResolveRequest(actions=[ReviewAction(item_id=row.id)]), None)
    with pytest.raises(ReviewError):
        resolve_review_task(world.session, summary.id, ResolveRequest(actions=[ReviewAction(item_id=row.id, village_id=987654)]), None)
    resolve_review_task(world.session, summary.id, ResolveRequest(actions=[ReviewAction(item_id=row.id, village_id=world.village["C"])]), None)
    assert world.session.scalars(select(VillageLocationAlias)).all() == []


def test_unknown_header_with_mapping_reparses_places_and_saves_mapping(world):
    summary = add_summary(world, [], text_value=TEXT)
    header = _row(world, summary, header_text="الاعتداءات الجديدة", location="الاعتداءات الجديدة",
                  evidence="الاعتداءات الجديدة", resolution=SummaryResolution.unknown_header)
    task = _task(world, summary, [{"type": "unknown_header", "item_ids": [header.id], "text": "الاعتداءات الجديدة"}])
    out = resolve_review_task(
        world.session, summary.id,
        ResolveRequest(actions=[ReviewAction(item_id=header.id, condition_ids=[world.condition["Bombs"]], save_mapping=True)]), None,
    )
    assert len(out.new_item_ids) == 2 and out.mapping_saved == ["الاعتداءات الجديدة"]
    new_items = [world.session.get(SummaryItem, i) for i in out.new_item_ids]
    assert {i.primary_village_id for i in new_items} == {world.village["A"], world.village["B"]}
    assert all(i.condition_id == world.condition["Bombs"] and i.resolution == SummaryResolution.resolved for i in new_items)
    mapping = world.session.scalar(select(SummaryHeaderMapping))
    assert mapping.header_text_normalized == "الاعتداءات الجديده" or "الاعتداءات" in mapping.header_text_normalized
    assert mapping.condition_ids == [world.condition["Bombs"]]
    assert task.status == SummaryReviewStatus.resolved
    assert world.session.get(SummaryItem, header.id).resolution == SummaryResolution.unknown_header  # bookkeeping row kept


def test_unknown_header_without_save_mapping_stores_nothing_permanent(world):
    summary = add_summary(world, [], text_value=TEXT)
    header = _row(world, summary, header_text="الاعتداءات الجديدة", location="الاعتداءات الجديدة",
                  evidence="الاعتداءات الجديدة", resolution=SummaryResolution.unknown_header)
    _task(world, summary, [{"type": "unknown_header", "item_ids": [header.id], "text": "x"}])
    out = resolve_review_task(
        world.session, summary.id, ResolveRequest(actions=[ReviewAction(item_id=header.id, condition_ids=[world.condition["Bombs"]])]), None
    )
    assert len(out.new_item_ids) == 2 and world.session.scalars(select(SummaryHeaderMapping)).all() == []


def test_casualty_dismiss_closes_item_without_incident(world):
    summary = add_summary(world, [{"village": "A", "evidence": "- كفرا شهيد"}])
    item = world.session.scalar(select(SummaryItem).where(SummaryItem.summary_id == summary.id))
    task = _task(world, summary, [{"type": "casualty_in_summary", "item_ids": [item.id], "text": item.evidence_span}])
    resolve_review_task(world.session, summary.id, ResolveRequest(actions=[ReviewAction(item_id=item.id, action="dismiss")]), None)
    assert item.reconciliation_status == SummaryReconciliationStatus.ambiguous
    assert world.session.scalars(select(Incident)).all() == [] and task.status == SummaryReviewStatus.resolved


def test_casualty_create_incident_still_writes_no_casualties(world):
    summary = add_summary(world, [{"village": "A", "evidence": "- كفرا شهيد"}])
    item = world.session.scalar(select(SummaryItem).where(SummaryItem.summary_id == summary.id))
    _task(world, summary, [{"type": "casualty_in_summary", "item_ids": [item.id], "text": item.evidence_span}])
    resolve_review_task(world.session, summary.id, ResolveRequest(actions=[ReviewAction(item_id=item.id, action="create_incident")]), None)
    incident = world.session.scalar(select(Incident))
    assert incident.origin == IncidentOrigin.summary and incident.source_summary_item_id == item.id
    assert (incident.deaths, incident.injuries, incident.total_deaths, incident.total_injuries) == (None, None, None, None)
    assert item.created_incident_id == incident.id and item.reconciliation_status == SummaryReconciliationStatus.created


def test_any_reason_can_be_dismissed_and_partial_resolution_keeps_task_open(world):
    summary, row, task = _unresolved_place_summary(world)
    second = _row(world, summary, location="ثانية", resolution=SummaryResolution.unresolved_location, position=91)
    task.reasons = [*task.reasons, {"type": "unresolved_location", "item_ids": [second.id], "text": "ثانية"}]
    world.session.flush()
    out = resolve_review_task(world.session, summary.id, ResolveRequest(actions=[ReviewAction(item_id=row.id, action="dismiss")]), None)
    assert out.task_status == "open" and task.status == SummaryReviewStatus.open
    assert row.resolution == SummaryResolution.unresolved_location  # dismissed, not resolved
    resolve_review_task(world.session, summary.id, ResolveRequest(actions=[
        ReviewAction(item_id=second.id, village_id=world.village["D"], condition_ids=[world.condition["Bombs"]])]), None)
    assert task.status == SummaryReviewStatus.resolved


def test_resolve_rejects_foreign_item_double_handling_and_closed_task(world):
    summary, row, task = _unresolved_place_summary(world)
    other = add_summary(world, [{"village": "B"}], channel="أخرى")
    foreign = world.session.scalar(select(SummaryItem).where(SummaryItem.summary_id == other.id))
    with pytest.raises(ReviewError) as caught:
        resolve_review_task(world.session, summary.id, ResolveRequest(actions=[ReviewAction(item_id=foreign.id, action="dismiss")]), None)
    assert caught.value.status == 404
    resolve_review_task(world.session, summary.id, ResolveRequest(actions=[ReviewAction(item_id=row.id, action="dismiss")]), None)
    with pytest.raises(ReviewError) as closed:
        resolve_review_task(world.session, summary.id, ResolveRequest(actions=[ReviewAction(item_id=row.id, action="dismiss")]), None)
    assert closed.value.status == 409


def test_invalid_action_for_reason_type_is_rejected(world):
    summary, row, _ = _unresolved_place_summary(world)
    with pytest.raises(ReviewError):
        resolve_review_task(world.session, summary.id, ResolveRequest(actions=[ReviewAction(item_id=row.id, action="create_incident")]), None)


def test_dismiss_endpoint_closes_the_task_and_requeues(world):
    summary, row, task = _unresolved_place_summary(world)
    dismiss_review_task(world.session, summary.id, None)
    assert task.status == SummaryReviewStatus.dismissed and summary.status == SummaryStatus.parsed
    with pytest.raises(ReviewError):
        dismiss_review_task(world.session, summary.id, None)


def test_request_model_rejects_empty_actions_and_empty_conditions():
    with pytest.raises(ValueError):
        ResolveRequest(actions=[])
    with pytest.raises(ValueError):
        ReviewAction(item_id=1, condition_ids=[])


# ---- incidents API exposes origin + summary --------------------------------------------------

def test_incident_list_and_detail_expose_origin_and_summary(world):
    from app.news.services.summaries.reconcile_service import reconcile_summary
    import asyncio

    from app.news.models import MessageStatus, RawMessage

    live = add_incident(world, village="B", condition="Bombs", at=at(7, 9))
    raw = RawMessage(source_id=world.source_id, raw_text="x", raw_payload={}, status=MessageStatus.materialized,
                     external_message_id="live-1", source_name="قناة حية")
    world.session.add(raw)
    world.session.flush()
    live.raw_message_id = raw.id
    summary = add_summary(world, [{"village": "A"}], channel="قناة اللائحة")
    asyncio.run(reconcile_summary(world.session, summary.id, dry_run=False))
    world.session.commit()
    repo = IncidentRepository(world.session)
    items = repo.list_all(IncidentListParams(event_date_from=date(2026, 10, 1), event_date_to=date(2026, 10, 31))).items
    by_origin = {i.origin: i for i in items}
    assert set(by_origin) == {"live", "summary"}
    summary_item = by_origin["summary"]
    assert summary_item.summary_id == summary.id and summary_item.summary_channel == "قناة اللائحة"
    assert summary_item.summary_window_end is not None and by_origin["live"].summary_id is None
    detail = repo.get_by_id(summary_item.id)
    assert detail.origin == "summary" and detail.summary_id == summary.id and detail.source_summary_item_id
