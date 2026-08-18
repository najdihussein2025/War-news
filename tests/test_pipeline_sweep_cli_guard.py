from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from app.core.scripts.run_pipeline_sweep_cli import (
    drain_pipeline_sweeps,
    main,
    pipeline_pass_is_idle,
)
from app.news.dtos.pipeline_dto import PipelineSweepResult, StageSweepResult


def _result(*, processed: int, skipped: bool = False) -> PipelineSweepResult:
    return PipelineSweepResult(
        skipped=skipped,
        skip_reason="pipeline_sweep_already_running" if skipped else None,
        stages=[
            StageSweepResult(
                stage="pre_extraction_dedup",
                processed=processed,
                succeeded=processed,
                failed=0,
                elapsed_seconds=0.1,
            )
        ],
        elapsed_seconds=0.1,
    )


def test_cli_refuses_foreground_run_in_api_role() -> None:
    with patch("app.core.scripts.run_pipeline_sweep_cli.settings") as settings:
        settings.pipeline_role = "api"
        assert main([]) == 2


def test_cli_enqueue_from_api_role(capsys) -> None:
    with (
        patch("app.core.scripts.run_pipeline_sweep_cli.settings") as settings,
        patch("app.core.scripts.run_pipeline_sweep_cli.SessionLocal") as session_local,
        patch(
            "app.core.scripts.run_pipeline_sweep_cli.enqueue_pipeline_sweep",
            return_value=17,
        ) as enqueue,
    ):
        settings.pipeline_role = "api"
        db = MagicMock()
        session_local.return_value.__enter__.return_value = db
        assert main(["--enqueue", "--once"]) == 0
        enqueue.assert_called_once()
    captured = capsys.readouterr()
    assert "job_id=17" in captured.out


def test_pipeline_pass_is_idle() -> None:
    assert pipeline_pass_is_idle(_result(processed=0)) is True
    assert pipeline_pass_is_idle(_result(processed=3)) is False
    assert pipeline_pass_is_idle(_result(processed=0, skipped=True)) is False


def test_drain_repeats_until_idle_pass() -> None:
    passes = [_result(processed=4), _result(processed=2), _result(processed=0)]

    async def fake_run(**kwargs):
        return passes.pop(0)

    with patch(
        "app.core.scripts.run_pipeline_sweep_cli._run_one_pass",
        side_effect=fake_run,
    ):
        assert asyncio.run(drain_pipeline_sweeps(max_rows=100)) == 0
    assert passes == []



def test_cli_refuses_foreground_run_in_api_role() -> None:
    with patch("app.core.scripts.run_pipeline_sweep_cli.settings") as settings:
        settings.pipeline_role = "api"
        assert main([]) == 2


def test_cli_enqueue_from_api_role(capsys) -> None:
    with (
        patch("app.core.scripts.run_pipeline_sweep_cli.settings") as settings,
        patch("app.core.scripts.run_pipeline_sweep_cli.SessionLocal") as session_local,
        patch(
            "app.core.scripts.run_pipeline_sweep_cli.enqueue_pipeline_sweep",
            return_value=17,
        ) as enqueue,
    ):
        settings.pipeline_role = "api"
        db = MagicMock()
        session_local.return_value.__enter__.return_value = db
        assert main(["--enqueue"]) == 0
        enqueue.assert_called_once()
    captured = capsys.readouterr()
    assert "job_id=17" in captured.out
