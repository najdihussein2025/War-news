from __future__ import annotations

import inspect
import logging
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.news.dtos.pipeline_dto import StageSweepResult
from app.news.models import MessageStatus, RawMessage
from app.news.services.fast_path_eligibility import ERROR_AIR_VIOLATION
from scripts import live_sweep_new_only as live_sweep


def _stage(name: str, *, processed: int = 2, failed: int = 0) -> StageSweepResult:
    return StageSweepResult(
        stage=name,
        processed=processed,
        succeeded=processed - failed,
        failed=failed,
        elapsed_seconds=0.01,
    )


def _aborted_stage(name: str, *, processed: int = 1, unprocessed: int = 5) -> StageSweepResult:
    return StageSweepResult(
        stage=name,
        processed=processed,
        succeeded=processed,
        failed=0,
        aborted=True,
        abort_reason="ollama_auth_failed_401",
        unprocessed=unprocessed,
        elapsed_seconds=0.01,
    )


def _bound_ids(statement) -> set[object]:
    compiled = statement.compile()
    return set(compiled.params.values())


def test_hardcoded_cutoff_constant_is_removed() -> None:
    assert not hasattr(live_sweep, "CUTOFF_RAW_MESSAGE_ID")
    assert "695974" not in inspect.getsource(live_sweep)
    assert not hasattr(live_sweep, "_cutoff_raw_message_id")


def test_relevance_query_uses_persisted_cursor_not_hardcoded_cutoff() -> None:
    repo = MagicMock()
    repo.db.scalars.return_value.all.return_value = []

    live_sweep._get_pending_unfiltered_batch_filtered(
        repo,
        10,
        cutoff_raw_message_id=42,
    )

    statement = repo.db.scalars.call_args.args[0]
    params = _bound_ids(statement)
    sql = str(statement.compile())
    assert 42 in params
    assert 695974 not in params
    assert "695974" not in sql


def test_downstream_claim_queries_do_not_use_cutoff() -> None:
    repo = MagicMock()
    repo.db.scalars.return_value.all.return_value = []
    repo.db.scalar.return_value = None

    live_sweep._claim_pending_pre_dedup_filtered(repo)
    pre_dedup_stmt = repo.db.scalar.call_args.args[0]

    live_sweep._claim_pending_extraction_filtered(repo)
    extraction_stmt = repo.db.scalar.call_args.args[0]

    live_sweep._claim_pending_match_filtered(repo)
    matching_stmt = repo.db.scalar.call_args.args[0]

    for statement in (pre_dedup_stmt, extraction_stmt, matching_stmt):
        params = _bound_ids(statement)
        sql = str(statement.compile())
        assert 42 not in params
        assert 695974 not in params
        assert "raw_messages.id >" not in sql


def test_filtered_session_uses_runtime_cursor() -> None:
    inner = MagicMock()
    wrapped = live_sweep.FilteredSession(inner, cutoff_raw_message_id=17)
    wrapped.scalars(select(RawMessage))
    filtered_stmt = inner.scalars.call_args.args[0]
    params = _bound_ids(filtered_stmt)
    assert 17 in params
    assert 695974 not in params


def test_advance_cursor_after_relevance_writes_max_processed_id(
    monkeypatch,
    caplog,
) -> None:
    persist = MagicMock()
    monkeypatch.setattr(live_sweep, "_persist_cursor", persist)

    with caplog.at_level(logging.INFO):
        assert (
            live_sweep._advance_cursor_after_relevance(
                previous_id=201,
                max_processed_id=1630,
            )
            == 1630
        )

    persist.assert_called_once_with(1630)
    assert any(
        "Live-sweep cursor advanced from=201 to=1630" in record.getMessage()
        for record in caplog.records
    )


def test_advance_cursor_after_relevance_does_not_insert_without_processed_ids(
    monkeypatch,
) -> None:
    persist = MagicMock()
    monkeypatch.setattr(live_sweep, "_persist_cursor", persist)

    assert (
        live_sweep._advance_cursor_after_relevance(
            previous_id=201,
            max_processed_id=None,
        )
        == 201
    )
    persist.assert_not_called()


def test_finish_stage_keeps_processed_succeeded_failed_shape(capsys) -> None:
    result = live_sweep._finish_stage(
        _stage("pre_extraction_dedup", processed=103),
        cutoff_raw_message_id=201,
    )
    assert result.processed == 103
    assert result.succeeded == 103
    assert result.failed == 0
    captured = capsys.readouterr()
    assert (
        "Pipeline stage=pre_extraction_dedup processed=103 succeeded=103 failed=0"
        in captured.out
    )


def test_finish_stage_prints_aborted_shape(capsys) -> None:
    live_sweep._finish_stage(
        _aborted_stage("tier1_extraction", processed=7, unprocessed=12),
        cutoff_raw_message_id=201,
    )
    captured = capsys.readouterr()
    assert "Pipeline stage=tier1_extraction aborted" in captured.out
    assert "unprocessed=12" in captured.out


@pytest.mark.asyncio
async def test_main_processes_above_persisted_cursor_and_advances(
    monkeypatch, caplog
) -> None:
    monkeypatch.setattr(live_sweep, "_load_cursor", lambda: 50)

    async def fake_stages(*, cutoff_raw_message_id: int) -> list[StageSweepResult]:
        assert cutoff_raw_message_id == 50
        return [_stage("relevance_filter", processed=3)]

    monkeypatch.setattr(live_sweep, "_run_stages", fake_stages)

    with caplog.at_level(logging.INFO):
        assert await live_sweep.main() == 0

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Starting one-pass new-only live sweep cutoff_raw_message_id=50" in message
        for message in messages
    )
    assert any(
        "Completed one-pass new-only live sweep cutoff_raw_message_id=50 advanced_to=50"
        in message
        for message in messages
    )


@pytest.mark.asyncio
async def test_cursor_read_failure_skips_run(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        live_sweep,
        "_load_cursor",
        MagicMock(side_effect=RuntimeError("cursor table missing")),
    )
    run_stages = MagicMock()
    monkeypatch.setattr(live_sweep, "_run_stages", run_stages)

    with caplog.at_level(logging.ERROR):
        assert await live_sweep.main() == 0

    run_stages.assert_not_called()
    assert any(
        "Failed to read live-sweep cursor" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_cursor_write_failure_skips_run_without_crashing(
    monkeypatch, caplog
) -> None:
    monkeypatch.setattr(live_sweep, "_load_cursor", lambda: 12)

    async def fail_stages(*, cutoff_raw_message_id: int) -> list[StageSweepResult]:
        raise RuntimeError("write failed")

    monkeypatch.setattr(live_sweep, "_run_stages", fail_stages)

    with caplog.at_level(logging.ERROR):
        assert await live_sweep.main() == 0

    assert any(
        "Live-sweep run failed cutoff_raw_message_id=12" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_run_stages_advances_cursor_to_relevance_processed_max(
    monkeypatch,
) -> None:
    persist = MagicMock()
    monkeypatch.setattr(live_sweep, "_persist_cursor", persist)

    async def fake_relevance_stage(
        *,
        cutoff_raw_message_id: int,
    ) -> tuple[StageSweepResult, int | None]:
        assert cutoff_raw_message_id == 201
        return _stage("relevance_filter", processed=2), 1630

    async def fake_async_stage(*args, **kwargs) -> StageSweepResult:
        return _stage("x")

    def fake_sync_stage(*args, **kwargs) -> StageSweepResult:
        return _stage("x")

    monkeypatch.setattr(live_sweep, "_run_relevance_stage", fake_relevance_stage)
    monkeypatch.setattr(live_sweep, "_run_async_stage", fake_async_stage)
    monkeypatch.setattr(live_sweep, "_run_sync_stage", fake_sync_stage)

    stages = await live_sweep._run_stages(cutoff_raw_message_id=201)

    assert stages[0].stage == "relevance_filter"
    persist.assert_called_once_with(1630)


@pytest.mark.asyncio
async def test_run_stages_stops_after_aborted_relevance(monkeypatch) -> None:
    async def fake_relevance_stage(
        *,
        cutoff_raw_message_id: int,
    ) -> tuple[StageSweepResult, int | None]:
        assert cutoff_raw_message_id == 201
        return _aborted_stage("relevance_filter"), None

    run_async = MagicMock()
    run_sync = MagicMock()
    persist = MagicMock()
    monkeypatch.setattr(live_sweep, "_persist_cursor", persist)
    monkeypatch.setattr(live_sweep, "_run_relevance_stage", fake_relevance_stage)
    monkeypatch.setattr(live_sweep, "_run_async_stage", run_async)
    monkeypatch.setattr(live_sweep, "_run_sync_stage", run_sync)

    stages = await live_sweep._run_stages(cutoff_raw_message_id=201)

    assert [stage.stage for stage in stages] == ["relevance_filter"]
    persist.assert_not_called()
    run_async.assert_not_called()
    run_sync.assert_not_called()


@pytest.mark.asyncio
async def test_run_stages_stops_after_aborted_tier1(monkeypatch) -> None:
    async def fake_relevance_stage(
        *,
        cutoff_raw_message_id: int,
    ) -> tuple[StageSweepResult, int | None]:
        return _stage("relevance_filter"), 1630

    async def fake_async_stage(stage_name: str, *args, **kwargs) -> StageSweepResult:
        if stage_name == "tier1_extraction":
            return _aborted_stage("tier1_extraction")
        return _stage(stage_name)

    run_sync = MagicMock()
    monkeypatch.setattr(live_sweep, "_run_relevance_stage", fake_relevance_stage)
    monkeypatch.setattr(live_sweep, "_run_async_stage", fake_async_stage)
    monkeypatch.setattr(live_sweep, "_run_sync_stage", run_sync)
    monkeypatch.setattr(live_sweep, "_persist_cursor", MagicMock())

    stages = await live_sweep._run_stages(cutoff_raw_message_id=201)

    assert [stage.stage for stage in stages] == [
        "relevance_filter",
        "pre_extraction_dedup",
        "tier1_extraction",
    ]
    run_sync.assert_not_called()


def test_downstream_stage_patches_leave_parsed_rows_visible_below_new_cutoff() -> None:
    raw_repo = MagicMock()
    raw_repo.db.scalars.return_value.all.return_value = []
    claim_repo = MagicMock()
    claim_repo.db.scalar.return_value = None

    with live_sweep._apply_downstream_stage_patches():
        live_sweep.RawMessageRepository.get_pending_extraction_batch(raw_repo, 10)
        live_sweep.PipelineClaimRepository.claim_pending_extraction(claim_repo)

    batch_stmt = raw_repo.db.scalars.call_args.args[0]
    claim_stmt = claim_repo.db.scalar.call_args.args[0]

    for statement in (batch_stmt, claim_stmt):
        params = _bound_ids(statement)
        sql = str(statement.compile())
        assert 1630 not in params
        assert "raw_messages.id >" not in sql
        assert "status" in sql.lower()


def test_terminalize_ineligible_fast_path_filtered_preserves_air_violation_status() -> None:
    message = MagicMock()
    message.match_result = {"matched_condition_id": 35}
    repo = MagicMock()
    repo.db.scalars.return_value.all.return_value = [message]

    updated = live_sweep._terminalize_ineligible_fast_path_filtered(repo)

    assert updated == 1
    assert message.status == MessageStatus.routed_air_violation
    assert message.error_message == ERROR_AIR_VIOLATION
    repo.db.add.assert_called_once_with(message)
    repo.db.commit.assert_called_once()
