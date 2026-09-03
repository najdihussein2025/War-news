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
from app.news.models import IncidentDetail
from app.news.services.tier2_detail_fill_service import Tier2DetailFillService


def test_fill_for_raw_message_merges_details_and_clears_pending() -> None:
    db = MagicMock()
    classifier = MagicMock()
    embedding_service = MagicMock()
    embedding_service.generate.return_value = [0.1, 0.2]

    extraction = ExtractionResult(
        is_relevant=True,
        village=["كفركلا"],
        casualties=ExtractionCasualties(deaths=1),
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
    )
    incident = SimpleNamespace(
        id="incident-1",
        raw_message_id=7,
        village_id=1,
        condition_id=2,
        event_date=datetime(2026, 8, 18).date(),
        deaths=1,
        injuries=None,
        total_deaths=None,
        total_injuries=None,
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
    )
    updated = service.apply_tier2_result_for_raw_message(
        7,
        tier2_categories=classifier.extract_tier2_details.return_value,
    )

    assert updated == 1
    assert incident.details_pending is False
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
        db, classifier, embedding_service=MagicMock(), dedup_service=None
    )
    updated = service.apply_tier2_result_for_raw_message(7, tier2_categories=None)

    assert updated == 0
    assert raw_message.tier2_completed_at is None
    db.commit.assert_not_called()
