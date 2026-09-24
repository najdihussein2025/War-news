"""4.5: pipeline health exposes failure counts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.news.dtos.pipeline_dto import PipelineFailureCountsResponse
from app.news.services.pipeline.pipeline_health_service import PipelineHealthService


def test_failure_counts_aggregate_error_stages_tier2_and_holds() -> None:
    db = MagicMock()
    oldest = datetime.now(timezone.utc) - timedelta(hours=2)
    db.execute.side_effect = [
        SimpleNamespace(all=lambda: [("relevance_filter", 3), ("tier1_extraction", 2), (None, 4)]),
        SimpleNamespace(one=lambda: (5, 1)),
    ]
    db.scalar.side_effect = [7, oldest]

    counts = PipelineHealthService(db).failure_counts()

    assert counts.error_rows_total == 9
    assert counts.error_rows_by_stage == {
        "relevance_filter": 3,
        "tier1_extraction": 2,
        "unknown": 4,
    }
    assert counts.tier2_retrying == 5
    assert counts.tier2_capped == 1
    assert counts.held_for_review == 7
    assert 7000 < counts.oldest_details_pending_seconds < 7300
    assert PipelineFailureCountsResponse(**vars(counts)).error_rows_total == 9
