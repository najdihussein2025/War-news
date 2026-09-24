from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from app.llm.dtos import ExtractionCategoryKey
from app.llm.services.ollama_extraction_service import OllamaExtractionService
from app.llm.services.transient_llm_errors import Tier2ExtractionFailedError
from app.news.services.extraction.tier2_detail_fill_service import Tier2DetailFillService


def _service_with_failing_detail(exc: BaseException) -> OllamaExtractionService:
    service = object.__new__(OllamaExtractionService)
    service.category_detail = MagicMock()
    service.category_detail.extract_detail.side_effect = exc
    service.category_detail.extract_details_batch.side_effect = exc
    return service


def test_extract_tier2_details_raises_on_transient_ollama_error() -> None:
    service = _service_with_failing_detail(httpx.ConnectError("connection refused"))

    with pytest.raises(Tier2ExtractionFailedError) as raised:
        service.extract_tier2_details(
            "خبر",
            [ExtractionCategoryKey.lebanese_army],
            raw_message_id=7,
        )

    assert raised.value.failed_categories == [ExtractionCategoryKey.lebanese_army.value]


def test_batched_tier2_raises_instead_of_returning_empty(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "tier2_use_batched_category_detail", True)
    service = _service_with_failing_detail(httpx.ReadTimeout("timed out"))

    with pytest.raises(Tier2ExtractionFailedError):
        service.extract_tier2_details(
            "خبر",
            [ExtractionCategoryKey.lebanese_army],
            raw_message_id=7,
        )


def _failure_fixture(retry_count: int):
    db = MagicMock()
    raw_message = SimpleNamespace(
        id=7,
        tier2_retry_count=retry_count,
        error_message=None,
        processing_claimed_at=None,
    )
    incident = SimpleNamespace(
        id="incident-1",
        details_pending=True,
        verification_status="auto_processed",
        verification_reason=None,
    )
    db.get.return_value = raw_message
    db.scalars.return_value.all.return_value = [incident]
    service = Tier2DetailFillService(
        db,
        MagicMock(),
        embedding_service=MagicMock(),
        dedup_service=None,
        emergency_org_matcher=MagicMock(),
        bulletin_groups=MagicMock(),
    )
    return service, raw_message, incident


def test_tier2_failure_below_cap_keeps_details_pending() -> None:
    service, raw_message, incident = _failure_fixture(retry_count=0)
    exc = Tier2ExtractionFailedError(["la"], httpx.ConnectError("refused"))

    capped = service.record_tier2_failure(7, exc, max_retries=3)

    assert capped is False
    assert raw_message.tier2_retry_count == 1
    assert incident.details_pending is True
    assert incident.verification_status == "auto_processed"
    assert raw_message.processing_claimed_at is not None


def test_tier2_failure_at_cap_flags_needs_verification_not_complete() -> None:
    service, raw_message, incident = _failure_fixture(retry_count=2)
    exc = Tier2ExtractionFailedError(["la"], httpx.ConnectError("refused"))

    capped = service.record_tier2_failure(7, exc, max_retries=3)

    assert capped is True
    assert raw_message.tier2_retry_count == 3
    assert incident.details_pending is True
    assert incident.verification_status == "needs_verification"
    assert "Tier 2 detail extraction failed after 3 retries" in incident.verification_reason


def test_worker_records_failure_and_does_not_apply_result(monkeypatch) -> None:
    from app.llm.dtos import ExtractionResult
    from app.news.services.pipeline import pipeline_llm_workers as workers
    from app.news.services.extraction import tier2_detail_fill_service as t2

    extraction = ExtractionResult(
        is_relevant=True,
        presence_category_keys=[ExtractionCategoryKey.lebanese_army],
        extraction_tier=1,
        model="test",
        extracted_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )
    message = SimpleNamespace(
        raw_text="خبر",
        extraction_result=extraction.model_dump(mode="json"),
    )
    session = MagicMock()
    session.__enter__.return_value = session
    monkeypatch.setattr(workers, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        workers,
        "RawMessageRepository",
        lambda db: SimpleNamespace(get_by_id=lambda _id: message),
    )
    classifier = MagicMock()
    classifier.extract_tier2_details.side_effect = Tier2ExtractionFailedError(
        ["la"], httpx.ConnectError("refused")
    )
    monkeypatch.setattr(workers, "build_extraction_classifier", lambda: classifier)
    recorded: list[int] = []
    applied: list[int] = []
    monkeypatch.setattr(
        t2.Tier2DetailFillService,
        "record_tier2_failure",
        lambda self, raw_message_id, exc: recorded.append(raw_message_id),
    )
    monkeypatch.setattr(
        t2.Tier2DetailFillService,
        "apply_tier2_result_for_raw_message",
        lambda self, raw_message_id, **_: applied.append(raw_message_id),
    )

    with pytest.raises(Tier2ExtractionFailedError):
        workers.run_tier2_detail_fill_for_message(7)

    assert recorded == [7]
    assert applied == []
