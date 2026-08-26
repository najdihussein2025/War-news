from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from app.news.dtos.pipeline_dto import StageSweepResult
from app.news.services import pipeline_orchestrator as orchestrator


def _ok(stage: str, *, failed: int = 0) -> StageSweepResult:
    processed = 2
    return StageSweepResult(
        stage=stage,
        processed=processed,
        succeeded=processed - failed,
        failed=failed,
        elapsed_seconds=0.01,
    )


def _aborted(stage: str) -> StageSweepResult:
    return StageSweepResult(
        stage=stage,
        processed=1,
        succeeded=1,
        failed=0,
        aborted=True,
        abort_reason="ollama_auth_failed_401",
        unprocessed=9,
        elapsed_seconds=0.01,
    )


def _patch_stages(monkeypatch, *, fail_stage: str | None = None) -> list[str]:
    calls: list[str] = []

    async def _async(name: str, *, max_rows: int | None = None):
        calls.append(name)
        if name == fail_stage:
            raise RuntimeError("stage exploded")
        return _ok(name)

    def _sync(name: str):
        def _run(db, *, max_rows: int | None = None):
            calls.append(name)
            if name == fail_stage:
                raise ValueError("")
            return _ok(name)

        return _run

    async def relevance(db, *, max_rows: int | None = None):
        return await _async("relevance_filter", max_rows=max_rows)

    monkeypatch.setattr(orchestrator, "SessionLocal", lambda: MagicMock())
    monkeypatch.setattr(orchestrator, "sweep_relevance_filter", relevance)
    monkeypatch.setattr(
        orchestrator,
        "sweep_pre_dedup_concurrent",
        lambda **kwargs: _async("pre_extraction_dedup", **kwargs),
    )
    monkeypatch.setattr(
        orchestrator,
        "sweep_extraction_concurrent",
        lambda **kwargs: _async("tier1_extraction", **kwargs),
    )
    monkeypatch.setattr(
        orchestrator,
        "sweep_matching_concurrent",
        lambda **kwargs: _async("matching", **kwargs),
    )
    monkeypatch.setattr(
        orchestrator,
        "sweep_fast_path_concurrent",
        lambda **kwargs: _async("fast_path", **kwargs),
    )
    monkeypatch.setattr(
        orchestrator,
        "sweep_tier2_detail_fill_concurrent",
        lambda **kwargs: _async("tier2_detail_fill", **kwargs),
    )
    monkeypatch.setattr(
        orchestrator, "sweep_embedding_generation", _sync("embedding")
    )
    monkeypatch.setattr(orchestrator, "sweep_clustering", _sync("clustering"))
    monkeypatch.setattr(
        orchestrator, "sweep_materialization", _sync("materialization")
    )
    return calls


@pytest.mark.asyncio
async def test_stage_exception_does_not_block_later_stages(monkeypatch, caplog) -> None:
    calls = _patch_stages(monkeypatch, fail_stage="tier1_extraction")

    with caplog.at_level(logging.WARNING):
        result = await orchestrator.run_full_pipeline_sweep(use_advisory_lock=False)

    assert "tier2_detail_fill" in calls
    assert "matching" in calls
    assert "fast_path" in calls
    assert "materialization" in calls
    assert result.partial_failure is True
    assert result.skipped is False
    failed = {stage.stage: stage.failed for stage in result.stages}
    assert failed["tier1_extraction"] == 1
    assert any(
        "Pipeline stage=tier1_extraction failed; continuing remaining stages"
        in record.message
        and "RuntimeError: stage exploded" in record.message
        for record in caplog.records
    )
    assert any(
        "Pipeline sweep completed with stage failures" in record.message
        and "tier1_extraction" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_item_failures_mark_sweep_partial_without_aborting(
    monkeypatch, caplog
) -> None:
    calls = _patch_stages(monkeypatch)

    async def extraction_with_item_failures(*, max_rows: int | None = None):
        calls.append("tier1_extraction")
        return _ok("tier1_extraction", failed=2)

    monkeypatch.setattr(
        orchestrator, "sweep_extraction_concurrent", extraction_with_item_failures
    )

    with caplog.at_level(logging.WARNING):
        result = await orchestrator.run_full_pipeline_sweep(use_advisory_lock=False)

    assert "tier2_detail_fill" in calls
    assert result.partial_failure is True
    assert any(
        "Pipeline stage=tier1_extraction completed with item failures" in record.message
        for record in caplog.records
    )
    assert any(
        "Pipeline sweep completed with stage failures" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_empty_stage_exception_message_is_logged(monkeypatch, caplog) -> None:
    calls = _patch_stages(monkeypatch, fail_stage="embedding")

    with caplog.at_level(logging.ERROR):
        result = await orchestrator.run_full_pipeline_sweep(use_advisory_lock=False)

    assert result.partial_failure is True
    assert "clustering" in calls
    assert "materialization" in calls
    assert any(
        "Pipeline stage=embedding failed; continuing remaining stages" in record.message
        and "ValueError (no message)" in record.message
        for record in caplog.records
    )
    assert any(stage.stage == "clustering" for stage in result.stages)
    assert any(stage.stage == "materialization" for stage in result.stages)


@pytest.mark.asyncio
async def test_auth_abort_stops_remaining_stages(monkeypatch, caplog) -> None:
    calls = _patch_stages(monkeypatch)

    async def aborted_extraction(*, max_rows: int | None = None):
        calls.append("tier1_extraction")
        return _aborted("tier1_extraction")

    monkeypatch.setattr(orchestrator, "sweep_extraction_concurrent", aborted_extraction)

    with caplog.at_level(logging.ERROR):
        result = await orchestrator.run_full_pipeline_sweep(use_advisory_lock=False)

    assert "matching" not in calls
    assert "tier2_detail_fill" not in calls
    assert result.partial_failure is True
    assert [stage.stage for stage in result.stages] == [
        "relevance_filter",
        "pre_extraction_dedup",
        "tier1_extraction",
    ]
    assert any(
        "Pipeline sweep aborted by Ollama authentication failure" in record.message
        for record in caplog.records
    )
