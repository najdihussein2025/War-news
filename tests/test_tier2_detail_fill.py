from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.llm.dtos import (
    ExtractionCasualties,
    ExtractionCategory,
    ExtractionCategoryKey,
    ExtractionResult,
)
from app.news.models import IncidentDetail, MessageStatus
from app.news.services.extraction.tier2_detail_fill_service import Tier2DetailFillService


def test_fill_for_raw_message_merges_details_and_clears_pending() -> None:
    db = MagicMock()
    classifier = MagicMock()
    embedding_service = MagicMock()
    embedding_service.generate.return_value = [0.1, 0.2]

    extraction = ExtractionResult(
        is_relevant=True,
        village=["كفركلا"],
        casualties=ExtractionCasualties(deaths=1, injuries=3),
        presence_category_keys=[ExtractionCategoryKey.lebanese_army],
        extraction_tier=1,
        model="test",
        extracted_at=datetime(2026, 8, 18, 11, 0, tzinfo=timezone.utc),
    )
    raw_message = SimpleNamespace(
        id=7,
        raw_text="خبر",
        extraction_result=extraction.model_dump(mode="json"),
        content_embedding=[0.1, 0.2],
        tier2_completed_at=None,
        match_result=None,
    )
    incident = SimpleNamespace(
        id="incident-1",
        raw_message_id=7,
        village_id=1,
        condition_id=2,
        event_date=datetime(2026, 8, 18).date(),
        deaths=1,
        injuries=0,
        total_deaths=0,
        total_injuries=0,
        khabar="خبر",
        khabar_embedding=None,
        details_pending=True,
        duplicate_flag=False,
        is_deleted=False,
    )
    detail = IncidentDetail(incident_id=uuid4())

    db.get.return_value = raw_message
    db.scalars.return_value.all.return_value = [incident]
    db.scalar.return_value = detail
    classifier.extract_tier2_details.return_value = {
        ExtractionCategoryKey.lebanese_army: ExtractionCategory(
            did=None,
            name=None,
            casualties=ExtractionCasualties(male_deaths=1),
        )
    }

    service = Tier2DetailFillService(
        db,
        classifier,
        embedding_service=embedding_service,
        dedup_service=None,
        emergency_org_matcher=MagicMock(),
    )
    updated = service.apply_tier2_result_for_raw_message(
        7,
        tier2_categories=classifier.extract_tier2_details.return_value,
    )

    assert updated == 1
    assert incident.details_pending is False
    assert incident.deaths == 1
    assert incident.injuries == 3
    assert incident.total_deaths == 2
    assert incident.total_injuries == 3
    assert raw_message.status == MessageStatus.materialized
    assert incident.khabar_embedding == [0.1, 0.2]
    assert raw_message.content_embedding == [0.1, 0.2]
    embedding_service.generate.assert_not_called()
    assert raw_message.extraction_result["extraction_tier"] == 2
    assert raw_message.tier2_completed_at is not None
    db.commit.assert_called_once()


def test_tier2_completed_at_left_none_when_no_pending_incidents() -> None:
    db = MagicMock()
    classifier = MagicMock()

    extraction = ExtractionResult(
        is_relevant=True,
        village=["كفركلا"],
        casualties=ExtractionCasualties(deaths=1),
        extraction_tier=2,
        model="test",
        extracted_at=datetime(2026, 8, 18, 11, 0, tzinfo=timezone.utc),
    )
    raw_message = SimpleNamespace(
        id=7,
        raw_text="خبر",
        extraction_result=extraction.model_dump(mode="json"),
        content_embedding=[0.1, 0.2],
        tier2_completed_at=None,
    )
    db.get.return_value = raw_message
    db.scalars.return_value.all.return_value = []

    service = Tier2DetailFillService(
        db,
        classifier,
        embedding_service=MagicMock(),
        dedup_service=None,
        emergency_org_matcher=MagicMock(),
    )
    updated = service.apply_tier2_result_for_raw_message(7, tier2_categories=None)

    assert updated == 0
    assert raw_message.tier2_completed_at is None
    db.commit.assert_not_called()


def _incident_stub(**overrides: object) -> SimpleNamespace:
    base = dict(
        id=uuid4(),
        raw_message_id=7,
        village_id=1,
        condition_id=2,
        event_date=datetime(2026, 8, 18).date(),
        event_time=None,
        deaths=None,
        injuries=None,
        total_deaths=None,
        total_injuries=None,
        khabar="خبر",
        duplicate_flag=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_tier2_high_score_backstop_canonicalizes_existing_incident() -> None:
    from app.core.config import settings

    dedup = MagicMock()
    peer = _incident_stub(id=uuid4(), raw_message_id=8)
    current = _incident_stub()
    dedup.find_best_match.return_value = (peer, settings.dedup_high_threshold)

    service = Tier2DetailFillService(
        MagicMock(),
        MagicMock(),
        embedding_service=MagicMock(),
        dedup_service=dedup,
        emergency_org_matcher=MagicMock(),
    )
    service._apply_dedup_backstop(
        current,
        embedding=[0.1, 0.2],
        raw_message_id=7,
        mapped_fields={},
        casualty_transitions=[],
    )

    dedup.canonicalize_existing_incident.assert_called_once_with(
        canonical=peer,
        duplicate=current,
        new_candidate_data={
            "deaths": current.deaths,
            "injuries": current.injuries,
            "total_deaths": current.total_deaths,
            "total_injuries": current.total_injuries,
            "khabar": current.khabar,
            "mapped_fields": {},
            "casualty_transitions": [],
        },
        similarity_score=settings.dedup_high_threshold,
    )
    dedup.record_possible_duplicate.assert_not_called()


def test_tier2_mid_score_backstop_records_duplicate_match_without_merge() -> None:
    from app.core.config import settings

    dedup = MagicMock()
    peer = _incident_stub(id=uuid4(), raw_message_id=8)
    current = _incident_stub()
    mid_score = (settings.dedup_low_threshold + settings.dedup_high_threshold) / 2.0
    dedup.find_best_match.return_value = (peer, mid_score)

    service = Tier2DetailFillService(
        MagicMock(),
        MagicMock(),
        embedding_service=MagicMock(),
        dedup_service=dedup,
        emergency_org_matcher=MagicMock(),
    )
    service._apply_dedup_backstop(
        current,
        embedding=[0.1, 0.2],
        raw_message_id=7,
        mapped_fields={},
        casualty_transitions=[],
    )

    dedup.merge_into_incident.assert_not_called()
    dedup.record_possible_duplicate.assert_called_once_with(
        incident=current,
        matched_incident=peer,
        similarity_score=mid_score,
    )
    assert current.duplicate_flag is True


def test_tier2_below_low_threshold_does_not_flag_or_record_match() -> None:
    from app.core.config import settings

    dedup = MagicMock()
    peer = _incident_stub(id=uuid4(), raw_message_id=8)
    current = _incident_stub()
    dedup.find_best_match.return_value = (peer, settings.dedup_low_threshold - 0.01)

    service = Tier2DetailFillService(
        MagicMock(),
        MagicMock(),
        embedding_service=MagicMock(),
        dedup_service=dedup,
        emergency_org_matcher=MagicMock(),
    )
    service._apply_dedup_backstop(
        current,
        embedding=[0.1, 0.2],
        raw_message_id=7,
        mapped_fields={},
        casualty_transitions=[],
    )

    dedup.merge_into_incident.assert_not_called()
    dedup.record_possible_duplicate.assert_not_called()
    assert current.duplicate_flag is False
