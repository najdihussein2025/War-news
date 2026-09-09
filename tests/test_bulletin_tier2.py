from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.llm.dtos import (
    CasualtyScope,
    DidValue,
    ExtractionCasualties,
    ExtractionCategory,
    ExtractionCategoryKey,
    ExtractionResult,
)
from app.news.models import IncidentDetail
from app.news.models.bulletin_casualty_group import CasualtyScope as StoredCasualtyScope
from app.news.services.extraction.tier2_detail_fill_service import Tier2DetailFillService


def test_tier2_stores_bulletin_total_without_backfilling_village() -> None:
    db = MagicMock()
    bulletin_groups = MagicMock()
    extraction = ExtractionResult(
        is_relevant=True,
        village=["النبطية", "كفررمان"],
        casualties=ExtractionCasualties(total_deaths=4, total_injuries=20),
        categories={
            ExtractionCategoryKey.lebanese_army: ExtractionCategory(
                did=DidValue.direct,
                casualties=ExtractionCasualties(male_deaths=2),
            )
        },
        casualty_scope=CasualtyScope.bulletin_aggregate,
        casualty_scope_evidence=(
            "حصيلة الغارات على النبطية وكفررمان بلغت 4 شهداء و20 جريحا"
        ),
        extraction_tier=2,
        model="test",
        extracted_at=datetime.now(timezone.utc),
    )
    message_datetime = datetime(2026, 9, 9, 8, 0, tzinfo=timezone.utc)
    raw_message = SimpleNamespace(
        id=7,
        raw_text=extraction.casualty_scope_evidence,
        extraction_result=extraction.model_dump(mode="json"),
        match_result={
            "village_matches": [
                {"matched_village_id": 10, "village_role": "target"},
                {"matched_village_id": 20, "village_role": "target"},
            ]
        },
        content_embedding=None,
        message_datetime=message_datetime,
        tier2_completed_at=None,
        materialized_at=None,
        status=None,
        error_message=None,
    )
    incident = SimpleNamespace(
        id=uuid4(),
        raw_message_id=7,
        village_id=10,
        condition_id=2,
        event_date=message_datetime.date(),
        event_time=message_datetime.time(),
        deaths=None,
        injuries=None,
        total_deaths=None,
        total_injuries=None,
        khabar=raw_message.raw_text,
        khabar_embedding=None,
        details_pending=True,
        duplicate_flag=False,
        is_deleted=False,
    )
    detail = IncidentDetail(incident_id=incident.id)
    db.get.return_value = raw_message
    db.scalars.return_value.all.return_value = [incident]
    db.scalar.return_value = detail

    service = Tier2DetailFillService(
        db,
        MagicMock(),
        embedding_service=MagicMock(),
        dedup_service=None,
        emergency_org_matcher=MagicMock(),
        bulletin_groups=bulletin_groups,
    )
    updated = service.apply_tier2_result_for_raw_message(
        raw_message.id,
        tier2_categories=None,
    )

    assert updated == 1
    assert (incident.deaths, incident.injuries) == (None, None)
    assert (incident.total_deaths, incident.total_injuries) == (None, None)
    assert detail.lam_d is None
    assert incident.verification_status == "needs_verification"
    assert "manual per-village confirmation" in incident.verification_reason
    bulletin_groups.create_for_message.assert_called_once_with(
        raw_message_id=7,
        village_ids=[10, 20],
        casualty_scope=StoredCasualtyScope.bulletin_aggregate,
        total_deaths=4,
        total_injuries=20,
        created_at=message_datetime,
    )
