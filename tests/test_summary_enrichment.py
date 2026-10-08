"""A live report arriving after a summary created the incident enriches it (scratch DB)."""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.llm.dtos import ExtractionCasualties, ExtractionResult
from app.news.models import Incident, IncidentOrigin, MessageStatus, RawMessage
from app.news.repositories.incident_repository import IncidentRepository
from app.news.services.dedup.fast_path_dedup import FastPathDedupService
from app.news.services.materialization import incident_materialization_service as ims
from app.news.services.materialization.incident_materialization_service import (
    SUMMARY_ENRICHED_NOTE,
    IncidentMaterializationService,
)
from app.news.services.summaries.reconcile_service import reconcile_summary
from tests.summary_db import add_summary, build_world

LIVE_TEXT = "غارة إسرائيلية على بلدة A أدت إلى سقوط شهيد"


@pytest.fixture
def world():
    w = build_world()
    yield w
    w.session.rollback()
    w.session.close()


def _live_message(world, *, hour: int = 15, condition: str = "Bombs", village: str = "A") -> RawMessage:
    when = datetime(2026, 10, 7, hour, 0, tzinfo=timezone.utc)
    extraction = ExtractionResult(
        is_relevant=True, village=[village], action_description="Bombs",
        casualties=ExtractionCasualties(deaths=1), model="test", extracted_at=when, extraction_tier=1,
    )
    message = RawMessage(
        source_id=world.source_id, raw_text=LIVE_TEXT, raw_payload={}, status=MessageStatus.parsed,
        external_message_id=f"live-{hour}-{village}", message_datetime=when,
        extraction_result=extraction.model_dump(mode="json"),
        match_result={
            "matched_condition_id": world.condition[condition], "condition_match_status": "matched",
            "village_matches": [{"matched_village_id": world.village[village], "village_match_status": "matched"}],
        },
    )
    world.session.add(message)
    world.session.flush()
    return message


def _summary_incident(world) -> Incident:
    summary = add_summary(world, [{"village": "A"}])
    asyncio.run(reconcile_summary(world.session, summary.id, dry_run=False))
    return world.session.scalar(select(Incident).where(Incident.origin == IncidentOrigin.summary))


def _process(world, message):
    service = IncidentMaterializationService(world.session)
    created = service.process_fast_path(message, FastPathDedupService(IncidentRepository(world.session)))
    return service, created


def test_live_message_enriches_summary_incident_instead_of_creating_a_new_one(world):
    summary_incident = _summary_incident(world)
    item_id = summary_incident.source_summary_item_id
    message = _live_message(world)
    _service, created = _process(world, message)

    incidents = world.session.scalars(select(Incident).where(Incident.village_id == world.village["A"])).all()
    assert len(incidents) == 1 and created == [incidents[0]]
    inc = incidents[0]
    assert inc.id == summary_incident.id
    assert inc.origin == IncidentOrigin.live and inc.source_summary_item_id == item_id
    assert inc.raw_message_id == message.id and inc.khabar.startswith("غارة إسرائيلية")
    assert (inc.event_time.hour, inc.event_date.day) == (18, 7)  # live time (UTC+3) replaces the window midpoint
    assert (inc.deaths, inc.total_deaths) == (1, 1)  # live casualties win
    assert SUMMARY_ENRICHED_NOTE in inc.note and "أُنشئ من ملخص" in inc.note
    assert inc.details_pending is True
    assert message.status == MessageStatus.materialized


def test_enrichment_matches_condition_family_and_same_day_only(world):
    _summary_incident(world)
    # different day -> a new incident, summary one untouched
    other_day = _live_message(world, hour=15)
    other_day.message_datetime = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc)
    other_day.external_message_id = "other-day"
    _process(world, other_day)
    origins = sorted(i.origin.value for i in world.session.scalars(select(Incident)))
    assert origins == ["live", "summary"]


def test_enrichment_is_not_triggered_by_a_live_incident(world):
    live = _live_message(world)
    _process(world, live)
    again = _live_message(world, hour=16)
    again.external_message_id = "again"
    service = IncidentMaterializationService(world.session)
    assert service.find_summary_incident(
        village_id=world.village["A"], condition_id=world.condition["Bombs"], event_datetime=datetime(2026, 10, 7, 19, 0)
    ) is None
    assert again.status == MessageStatus.parsed


def test_summary_created_incidents_have_no_casualties_or_verification_flag(world):
    inc = _summary_incident(world)
    assert (inc.deaths, inc.injuries, inc.total_deaths, inc.total_injuries) == (None, None, None, None)
    assert inc.verification_status == "auto_processed" and inc.verification_reason is None
    assert inc.duplicate_flag is False


def test_enrich_and_create_signatures_are_stable():
    """Wrapper/service drift caused silent failures before: pin the new entry points."""
    create = inspect.signature(IncidentMaterializationService.create_summary_incident).parameters
    assert set(create) == {
        "self", "village_id", "condition_id", "event_datetime", "khabar", "note", "source_id",
        "source_summary_item_id", "hash_suffix", "village_display_name",
    }
    enrich = inspect.signature(IncidentMaterializationService.enrich_summary_incident).parameters
    assert {"incident", "representative", "extraction", "village_casualties", "event_datetime"} <= set(enrich)
    find = inspect.signature(IncidentMaterializationService.find_summary_incident).parameters
    assert list(find) == ["self", "village_id", "condition_id", "event_datetime"]
    assert ims.SUMMARY_ENRICHED_NOTE
