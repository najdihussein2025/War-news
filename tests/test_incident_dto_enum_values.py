"""Every enum value present in the real data must validate through the read DTOs.

Values come from a read-only SELECT DISTINCT on war_news_dev (2026-09-28), not a DB connection.
"""
import logging
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from app.news.dtos.incident_dto import (
    BulletinCasualtyGroupDTO,
    IncidentDetailDTO,
    IncidentListItemDTO,
    IncidentListResponse,
)

REAL_DUPLICATE_LEVELS = [None, "low", "medium", "high", "segment"]
REAL_VERIFICATION_STATUSES = ["auto_processed", "needs_verification", "rejected"]
REAL_BCG = [("bulletin_aggregate", "expired"), ("bulletin_aggregate", "pending")]


def _list_item(**overrides):
    row = {
        "id": uuid4(), "raw_message_id": 1, "raw_status": "materialized", "village": "Rmadiye",
        "condition": "Airstrike", "event_date": date(2026, 9, 4), "khabar": "text", "source": "Telegram",
        "source_reference": None, "matched": True, "duplicate_flag": "none", "details_pending": False,
        "created_at": datetime(2026, 9, 4, tzinfo=timezone.utc),
    }
    return {**row, **overrides}


def _detail(**overrides):
    row = {
        "id": uuid4(), "village": "Rmadiye", "condition": "Airstrike", "source": "Telegram",
        "source_reference": None, "khabar": "text", "note": None, "moh": None, "martyrs": None,
        "worker_name": None, "source_link": None, "source_link_2": None, "total_deaths": None,
        "total_injuries": None, "deaths": None, "injuries": None, "event_date": date(2026, 9, 4),
        "event_time": None, "created_at": datetime(2026, 9, 4, tzinfo=timezone.utc), "matched": True,
        "duplicate_flag": "possible",
        "casualty_demographics": {k: None for k in ("male_d", "male_i", "female_d", "female_i", "children_d", "children_i")},
        "casualties": {"killed": None, "injured": None, "status": "none"},
    }
    return {**row, **overrides}


@pytest.mark.parametrize("level", REAL_DUPLICATE_LEVELS)
def test_real_duplicate_levels_validate_in_list_and_detail(level):
    assert IncidentListItemDTO.model_validate(_list_item(duplicate_level=level)).duplicate_level == level
    assert IncidentDetailDTO.model_validate(_detail(duplicate_level=level)).duplicate_level == level


@pytest.mark.parametrize("status", REAL_VERIFICATION_STATUSES)
def test_real_verification_statuses_validate(status):
    assert IncidentListItemDTO.model_validate(_list_item(verification_status=status)).verification_status == status
    assert IncidentDetailDTO.model_validate(_detail(verification_status=status)).verification_status == status


@pytest.mark.parametrize(("scope", "breakdown"), REAL_BCG)
def test_real_bulletin_group_values_validate(scope, breakdown):
    group = BulletinCasualtyGroupDTO.model_validate({
        "casualty_scope": scope, "total_deaths": 3, "total_injuries": 23, "breakdown_status": breakdown,
        "window_expires_at": None, "resolved_at": None, "resolved_by_raw_message_id": None,
    })
    assert group.breakdown_status == breakdown


def test_segment_duplicate_serializes_through_list_response():
    response = IncidentListResponse(items=[IncidentListItemDTO.model_validate(_list_item(duplicate_level="segment"))], total=1, limit=150)
    assert response.model_dump(mode="json")["items"][0]["duplicate_level"] == "segment"


def test_unknown_duplicate_level_does_not_fail_the_page(caplog):
    with caplog.at_level(logging.WARNING, logger="app.news.dtos.incident_dto"):
        rows = [IncidentListItemDTO.model_validate(_list_item(duplicate_level=value)) for value in ("high", "cluster_v2")]
        detail = IncidentDetailDTO.model_validate(_detail(duplicate_level="cluster_v2"))
    assert [row.duplicate_level for row in rows] == ["high", None]
    assert detail.duplicate_level is None
    assert "cluster_v2" in caplog.text
