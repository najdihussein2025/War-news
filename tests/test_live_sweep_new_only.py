from __future__ import annotations

import inspect
import logging
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.news.dtos.pipeline_dto import StageSweepResult
from app.news.models import RawMessage
from scripts import live_sweep_new_only as live_sweep


def _stage(name: str, *, processed: int = 2, failed: int = 0) -> StageSweepResult:
    return StageSweepResult(
        stage=name,
        processed=processed,
        succeeded=processed - failed,
        failed=failed,
        elapsed_seconds=0.01,
    )


def _bound_ids(statement) -> set[object]:
    compiled = statement.compile()
    return set(compiled.params.values())


def test_hardcoded_cutoff_constant_is_removed() -> None:
    assert not hasattr(live_sweep, "CUTOFF_RAW_MESSAGE_ID")
    assert "695974" not in inspect.getsource(live_sweep)


def test_claim_queries_use_persisted_cursor_not_hardcoded_cutoff() -> None:
    live_sweep._cutoff_raw_message_id = 42
    repo = MagicMock()
    repo.db.scalars.return_value.all.return_value = []
    repo.db.scalar.return_value = None

    live_sweep._get_pending_unfiltered_batch_filtered(repo, 10)
    live_sweep._claim_pending_match_filtered(repo)

    unfiltered_stmt = repo.db.scalars.call_args.args[0]
    match_stmt = repo.db.scalar.call_args.args[0]
    for statement in (unfiltered_stmt, match_stmt):
        params = _bound_ids(statement)
        sql = str(statement.compile())
        assert 42 in params
        assert 695974 not in params
        assert "695974" not in sql


def test_filtered_session_uses_runtime_cursor() -> None:
    inner = MagicMock()
    wrapped = live_sweep.FilteredSession(inner, cutoff_raw_message_id=17)
    wrapped.scalars(select(RawMessage))
    filtered_stmt = inner.scalars.call_args.args[0]
    params = _bound_ids(filtered_stmt)
    assert 17 in params
    assert 695974 not in params


def test_next_cursor_stops_before_retryable_open_row() -> None:
    assert (
        live_sweep.next_cursor_value(
            previous_id=50,
            min_open_id=60,
            max_id_above=100,
        )
        == 59
    )


def test_next_cursor_does_not_advance_when_first_open_row_is_next() -> None:
    assert (
        live_sweep.next_cursor_value(
            previous_id=50,
            min_open_id=51,
            max_id_above=100,
        )
        == 50
    )


def test_next_cursor_advances_to_max_when_caught_up() -> None:
    assert (
        live_sweep.next_cursor_value(
            previous_id=50,
            min_open_id=None,
            max_id_above=80,
        )
        == 80
    )


def test_next_cursor_never_moves_backwards() -> None:
    assert (
        live_sweep.next_cursor_value(
            previous_id=50,
            min_open_id=10,
            max_id_above=80,
        )
        == 50
    )


def test_compute_next_cursor_uses_open_row_prefix() -> None:
    db = MagicMock()
    db.scalar.side_effect = [60, 100]
    assert live_sweep.compute_next_cursor(db, 50) == 59


def test_compute_next_cursor_advances_from_zero_past_leading_terminal_rows() -> None:
    """Regression: ids 1-201 terminal, first open parsed at 202 -> cursor 201."""
    db = MagicMock()
    db.scalar.side_effect = [202, 290]
    assert live_sweep.compute_next_cursor(db, 0) == 201


def test_compute_next_cursor_unchanged_when_immediate_next_row_still_open() -> None:
    db = MagicMock()
    db.scalar.side_effect = [51, 100]
    assert live_sweep.compute_next_cursor(db, 50) == 50


def test_refresh_persisted_cursor_advances_in_process_cutoff(monkeypatch, caplog) -> None:
    live_sweep._cutoff_raw_message_id = 0
    monkeypatch.setattr(live_sweep, "_advance_and_persist_cursor", lambda previous: 201)

    with caplog.at_level(logging.INFO):
        assert live_sweep._refresh_persisted_cursor() == 201

    assert live_sweep._cutoff_raw_message_id == 201
    assert any(
        "Live-sweep cursor advanced from=0 to=201" in record.getMessage()
        for record in caplog.records
    )


def test_finish_stage_keeps_processed_succeeded_failed_shape(monkeypatch, capsys) -> None:
    monkeypatch.setattr(live_sweep, "_refresh_persisted_cursor", lambda **kwargs: 0)
    result = live_sweep._finish_stage(_stage("pre_extraction_dedup", processed=103))
    assert result.processed == 103
    assert result.succeeded == 103
    assert result.failed == 0
    captured = capsys.readouterr()
    assert (
        "Pipeline stage=pre_extraction_dedup processed=103 succeeded=103 failed=0"
        in captured.out
    )


@pytest.mark.asyncio
async def test_main_processes_above_persisted_cursor_and_advances(
    monkeypatch, caplog
) -> None:
    monkeypatch.setattr(live_sweep, "_load_cursor", lambda: 50)
    monkeypatch.setattr(live_sweep, "_advance_and_persist_cursor", lambda previous: 80)

    async def fake_stages() -> list[StageSweepResult]:
        assert live_sweep._cutoff_raw_message_id == 80
        return [_stage("relevance_filter", processed=3)]

    monkeypatch.setattr(live_sweep, "_run_stages", fake_stages)

    with caplog.at_level(logging.INFO):
        assert await live_sweep.main() == 0

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Starting one-pass new-only live sweep cutoff_raw_message_id=50" in message
        for message in messages
    )
    assert any("Live-sweep cursor advanced from=50 to=80" in message for message in messages)
    assert any(
        "Completed one-pass new-only live sweep cutoff_raw_message_id=50 advanced_to=80"
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
    run_stages = MagicMock()
    monkeypatch.setattr(live_sweep, "_run_stages", run_stages)
    monkeypatch.setattr(
        live_sweep,
        "_advance_and_persist_cursor",
        MagicMock(side_effect=RuntimeError("write failed")),
    )

    with caplog.at_level(logging.ERROR):
        assert await live_sweep.main() == 0

    run_stages.assert_not_called()
    assert any(
        "Failed to persist live-sweep cursor" in record.getMessage()
        for record in caplog.records
    )


def test_advance_and_persist_cursor_writes_only_when_advanced(monkeypatch) -> None:
    db = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db
    session_cm.__exit__.return_value = False
    monkeypatch.setattr(live_sweep, "SessionLocal", lambda: session_cm)
    monkeypatch.setattr(live_sweep, "compute_next_cursor", lambda _db, previous: 20)
    persist = MagicMock()
    monkeypatch.setattr(live_sweep, "_persist_cursor", persist)

    assert live_sweep._advance_and_persist_cursor(10) == 20
    persist.assert_called_once_with(20)

    persist.reset_mock()
    monkeypatch.setattr(live_sweep, "compute_next_cursor", lambda _db, previous: 10)
    assert live_sweep._advance_and_persist_cursor(10) == 10
    persist.assert_not_called()
