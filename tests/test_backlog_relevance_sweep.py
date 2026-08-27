from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from app.news.dtos.pipeline_dto import StageSweepResult
from app.news.repositories.raw_message_repository import RawMessageRepository
from scripts import backlog_relevance_sweep as backlog_sweep


def _stage(*, processed: int = 3, failed: int = 1) -> StageSweepResult:
    return StageSweepResult(
        stage="relevance_filter",
        processed=processed,
        succeeded=processed - failed,
        failed=failed,
        elapsed_seconds=0.01,
    )


def _aborted_stage(*, processed: int = 1, unprocessed: int = 4) -> StageSweepResult:
    return StageSweepResult(
        stage="relevance_filter",
        processed=processed,
        succeeded=processed,
        failed=0,
        aborted=True,
        abort_reason="ollama_auth_failed_401",
        unprocessed=unprocessed,
        elapsed_seconds=0.01,
    )


def _session_factory(session: MagicMock) -> MagicMock:
    factory = MagicMock()
    factory.return_value.__enter__ = MagicMock(return_value=session)
    factory.return_value.__exit__ = MagicMock(return_value=False)
    return factory


def test_main_runs_relevance_sweep_without_cutoff_patches(monkeypatch) -> None:
    session = MagicMock()
    seen: dict[str, object] = {}
    original_batch = RawMessageRepository.get_pending_unfiltered_batch

    async def fake_sweep(db, *, max_rows=None):
        seen["db"] = db
        seen["max_rows"] = max_rows
        seen["batch_method"] = RawMessageRepository.get_pending_unfiltered_batch
        return _stage()

    monkeypatch.setattr(backlog_sweep, "SessionLocal", _session_factory(session))
    monkeypatch.setattr(backlog_sweep, "sweep_relevance_filter", fake_sweep)
    monkeypatch.setattr(backlog_sweep, "configure_logging", MagicMock())

    assert asyncio.run(backlog_sweep.main()) == 0

    assert seen["db"] is session
    assert seen["max_rows"] is backlog_sweep.MAX_ROWS
    assert seen["batch_method"] is original_batch


def test_main_emits_summary_line(monkeypatch, capsys) -> None:
    async def fake_sweep(db, *, max_rows=None):
        return _stage(processed=5, failed=2)

    monkeypatch.setattr(backlog_sweep, "SessionLocal", _session_factory(MagicMock()))
    monkeypatch.setattr(backlog_sweep, "sweep_relevance_filter", fake_sweep)
    monkeypatch.setattr(backlog_sweep, "configure_logging", MagicMock())

    assert asyncio.run(backlog_sweep.main()) == 0

    out = capsys.readouterr().out
    assert "stage=relevance_filter" in out
    assert "processed=5" in out
    assert "succeeded=3" in out
    assert "failed=2" in out


def test_main_emits_aborted_summary_line(monkeypatch, capsys) -> None:
    async def fake_sweep(db, *, max_rows=None):
        return _aborted_stage(processed=1, unprocessed=4)

    monkeypatch.setattr(backlog_sweep, "SessionLocal", _session_factory(MagicMock()))
    monkeypatch.setattr(backlog_sweep, "sweep_relevance_filter", fake_sweep)
    monkeypatch.setattr(backlog_sweep, "configure_logging", MagicMock())

    assert asyncio.run(backlog_sweep.main()) == 0

    out = capsys.readouterr().out
    assert "aborted" in out
    assert "unprocessed=4" in out


def test_main_returns_zero_when_sweep_raises(monkeypatch, capsys) -> None:
    async def fake_sweep(db, *, max_rows=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(backlog_sweep, "SessionLocal", _session_factory(MagicMock()))
    monkeypatch.setattr(backlog_sweep, "sweep_relevance_filter", fake_sweep)
    monkeypatch.setattr(backlog_sweep, "configure_logging", MagicMock())

    assert asyncio.run(backlog_sweep.main()) == 0
    assert "stage=relevance_filter" not in capsys.readouterr().out
