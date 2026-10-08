"""Live/shadow routing of summary bulletins around Tier 1 (no database needed)."""
from __future__ import annotations

import asyncio
import inspect
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.llm.actions.extract_incidents_action import ExtractIncidentsAction
from app.llm.dtos import ExtractionResult
from app.news.models import MessageStatus
from app.news.models.summary_bulletin import SummaryStatus
from app.news.services.pipeline import pipeline_llm_workers as workers
from app.news.services.summaries import intake_service, routing
from app.news.services.summaries.gazetteer import GazetteerSnapshot
from app.news.services.summaries.intake_service import SummaryIntakeResult


def _message(status=MessageStatus.parsed) -> SimpleNamespace:
    return SimpleNamespace(
        id=7, raw_text="ملخص", status=status, extraction_result=None, error_message="old",
        processing_claim_stage="tier1", processing_claimed_at=datetime.now(timezone.utc), processing_claimed_by="w",
        cnrs_classification=None,
    )


class _Session:
    def __init__(self, existing=None):
        self.existing, self.added, self.commits, self.rollbacks = existing, [], 0, 0

    def add(self, obj): self.added.append(obj)
    def flush(self): pass
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1
    def scalar(self, *_a, **_k): return self.existing


def _patch_intake(monkeypatch, outcome: str, summary_id: int | None = 5):
    async def fake(session, message):
        return SummaryIntakeResult(outcome, summary_id)
    monkeypatch.setattr(routing, "intake_summary", fake)


@pytest.mark.parametrize("outcome", ["parsed", "needs_review", "skipped_repost", "awaiting_window"])
def test_live_routes_real_summary_away_from_tier1(monkeypatch, outcome):
    _patch_intake(monkeypatch, outcome)
    message = _message()
    decision = routing.route_summary(_Session(), message, mode="live")
    assert decision.handled and decision.outcome == outcome
    assert message.status == MessageStatus.summary_handled
    assert message.processing_claim_stage is None and message.processing_claimed_by is None
    assert message.error_message is None


@pytest.mark.parametrize("outcome", ["not_summary", "not_a_summary", "failed"])
def test_live_falls_back_to_tier1_when_not_a_usable_summary(monkeypatch, outcome):
    _patch_intake(monkeypatch, outcome)
    message = _message()
    decision = routing.route_summary(_Session(), message, mode="live")
    assert not decision.handled
    assert message.status == MessageStatus.parsed


def test_live_previously_failed_summary_falls_back(monkeypatch):
    _patch_intake(monkeypatch, "already_processed")
    session = _Session(existing=SimpleNamespace(status=SummaryStatus.failed))
    assert not routing.route_summary(session, _message(), mode="live").handled


def test_shadow_never_handles_and_off_never_runs_intake(monkeypatch):
    _patch_intake(monkeypatch, "parsed")
    message = _message()
    assert not routing.route_summary(_Session(), message, mode="shadow").handled
    assert message.status == MessageStatus.parsed

    async def boom(*_a, **_k):
        raise AssertionError("intake must not run when the flow is off")
    monkeypatch.setattr(routing, "intake_summary", boom)
    assert not routing.route_summary(_Session(), message, mode="off").handled


def test_summary_handled_is_selected_by_no_sweep_status():
    """Every sweep selects on pending / parsed / error; summary_handled is none of them."""
    import re
    from pathlib import Path

    selected = set()
    for rel in (
        "app/news/repositories/pipeline_claim_repository.py", "app/news/repositories/raw_message_repository.py",
        "scripts/live_sweep_new_only.py", "app/news/services/clustering/clustering_service.py",
    ):
        selected |= set(re.findall(r"RawMessage\.status\s*(?:==|\.in_\(\[?)\s*MessageStatus\.(\w+)", Path(rel).read_text(encoding="utf-8")))
    assert "summary_handled" not in selected and selected <= {"pending", "parsed", "error", "duplicate", "rejected", "materialized"}


class _Classifier:
    def __init__(self): self.calls = 0
    def extract_tier1(self, *, post_text, raw_message_id):
        self.calls += 1
        return ExtractionResult(is_relevant=True, village=["x"], action_description="Bombs", model="t", extracted_at=datetime.now(timezone.utc))


class _Repo:
    def __init__(self, message): self.message, self.saved = message, 0
    def get_pending_extraction_batch(self, limit): return [self.message]
    def get_by_id(self, _id): return self.message
    def save_extraction_result(self, *, message, result, audited_candidates):
        self.saved += 1
        message.extraction_result = result.model_dump(mode="json")
    def rollback(self): pass


def test_sequential_extraction_skips_tier1_for_handled_summary():
    repo, classifier = _Repo(_message()), _Classifier()
    action = ExtractIncidentsAction(repo, classifier, summary_router=lambda m: True)
    summary = action.execute(SimpleNamespace(batch_size=1))
    assert classifier.calls == 0 and repo.saved == 0 and summary.processed == 1
    action.execute_one(7)
    assert classifier.calls == 0


def test_sequential_extraction_runs_tier1_when_router_declines_or_absent():
    for router in (lambda m: False, None):
        repo, classifier = _Repo(_message()), _Classifier()
        ExtractIncidentsAction(repo, classifier, summary_router=router).execute(SimpleNamespace(batch_size=1))
        assert classifier.calls == 1 and repo.saved == 1


def test_extract_action_signature_accepts_summary_router():
    params = inspect.signature(ExtractIncidentsAction.__init__).parameters
    assert "summary_router" in params and params["summary_router"].default is None


def test_factory_passes_summary_router_to_the_action():
    from app.api.factories import action_factory
    source = inspect.getsource(action_factory.build_extract_incidents_action)
    assert "summary_router=build_summary_router(db)" in source


@contextmanager
def _session_cm(session):
    yield session


def _patch_worker(monkeypatch, message, outcome_handled: bool):
    session = _Session()
    monkeypatch.setattr(workers, "SessionLocal", lambda: _session_cm(session))
    monkeypatch.setattr(workers, "RawMessageRepository", lambda db: SimpleNamespace(get_by_id=lambda _i: message, save_extraction_result=lambda **k: None))
    monkeypatch.setattr(workers.settings, "summary_flow_mode", "live")
    monkeypatch.setattr(
        routing, "route_summary", lambda db, m, mode=None: routing.SummaryRouting(outcome_handled, "parsed", 5)
    )
    classifier = _Classifier()
    monkeypatch.setattr(workers, "build_extraction_classifier", lambda: classifier)
    return session, classifier


def test_tier1_worker_returns_before_classifier_for_handled_summary(monkeypatch):
    session, classifier = _patch_worker(monkeypatch, _message(), True)
    workers.run_tier1_extraction_for_message(7)
    assert classifier.calls == 0 and session.commits == 1


def test_tier1_worker_continues_to_tier1_when_summary_not_handled(monkeypatch):
    session, classifier = _patch_worker(monkeypatch, _message(), False)
    workers.run_tier1_extraction_for_message(7)
    assert classifier.calls == 1


def test_tier1_worker_survives_a_crashing_summary_flow(monkeypatch):
    session, classifier = _patch_worker(monkeypatch, _message(), False)

    def crash(*_a, **_k):
        raise RuntimeError("boom")
    monkeypatch.setattr(routing, "route_summary", crash)
    workers.run_tier1_extraction_for_message(7)
    assert classifier.calls == 1 and session.rollbacks == 1


# ---- false-positive guard (real parser, empty gazetteer, no DB) ------------------

NEWS_WITH_SUMMARY_WORD = (
    "ملخص ما حدث اليوم: شنت الطائرات الحربية الإسرائيلية غارة على أطراف بلدة عيتا الشعب جنوب لبنان."
)


def test_news_item_mentioning_summary_is_not_a_summary(monkeypatch):
    monkeypatch.setattr(intake_service, "detect_summary", lambda text: SimpleNamespace(is_summary=True))
    monkeypatch.setattr(intake_service, "build_gazetteer_snapshot", lambda session: GazetteerSnapshot({}))
    session = _Session()
    message = SimpleNamespace(
        id=9, raw_text=NEWS_WITH_SUMMARY_WORD, source_id=1, source_name="قناة",
        message_datetime=datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc), received_at=None,
    )
    result = asyncio.run(intake_service.intake_summary(session, message))
    assert result.outcome == "not_a_summary" and result.error == "not_a_summary"
    summary = session.added[0]
    assert summary.status == SummaryStatus.failed and summary.last_error == "not_a_summary"
    assert len(session.added) == 1  # no items, no review task


def test_intake_signature_and_return_shape_are_stable():
    assert list(inspect.signature(intake_service.intake_summary).parameters) == ["session", "raw_message"]
    assert list(inspect.signature(routing.route_summary).parameters) == ["session", "message", "mode"]
