from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.llm.dtos import ExtractionCasualties, ExtractionResult
from app.news.services.tier2_detail_fill_service import Tier2DetailFillService


def test_tier2_failure_preserves_precomputed_embedding() -> None:
    classifier = MagicMock()
    classifier.extract_tier2_details.side_effect = RuntimeError("tier2 failed")
    embedding_service = MagicMock()

    extraction = ExtractionResult(
        is_relevant=True,
        village=["كفركلا"],
        casualties=ExtractionCasualties(deaths=1),
        extraction_tier=1,
        model="test",
        extracted_at=datetime(2026, 8, 18, 11, 0, tzinfo=timezone.utc),
    )
    raw_message = SimpleNamespace(
        id=7,
        raw_text="خبر",
        extraction_result=extraction.model_dump(mode="json"),
        content_embedding=[0.5, 0.6],
    )
    db = MagicMock()
    db.get.return_value = raw_message

    service = Tier2DetailFillService(
        db,
        classifier,
        embedding_service=embedding_service,
        dedup_service=None,
    )

    with pytest.raises(RuntimeError, match="tier2 failed"):
        service.fill_for_raw_message(7)

    assert raw_message.content_embedding == [0.5, 0.6]
    embedding_service.generate.assert_not_called()
