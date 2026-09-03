from __future__ import annotations

import argparse
import asyncio
import sys
import time

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging_config import configure_logging
from app.news.dtos.pipeline_dto import PipelineSweepResult, StageSweepResult
from app.news.services.pipeline_jobs import enqueue_pipeline_sweep
from app.news.services.pipeline_orchestrator import (
    pipeline_pass_is_idle,
    run_full_pipeline_sweep,
)


def _print_stage(result: StageSweepResult) -> None:
    print(
        f"Pipeline stage={result.stage} processed={result.processed} "
        f"succeeded={result.succeeded} failed={result.failed} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}",
        flush=True,
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run or enqueue a pipeline sweep. Foreground runs are refused inside "
            "the reloading backend container; enqueue for the dedicated worker."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Optional cap on eligible rows processed per stage (same as ?limit=).",
    )
    parser.add_argument(
        "--enqueue",
        action="store_true",
        help="Insert a job for pipeline-worker instead of running in this process.",
    )
    parser.add_argument(
        "--drain",
        action="store_true",
        help=(
            "Repeat full sweeps until a pass processes zero rows across all stages. "
            "This is the default for foreground runs."
        ),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single capped pass and exit instead of draining.",
    )
    return parser.parse_args(argv)


async def _run_one_pass(*, max_rows: int | None) -> PipelineSweepResult:
    return await run_full_pipeline_sweep(
        max_rows=max_rows,
        use_advisory_lock=True,
        on_stage=_print_stage,
    )


async def drain_pipeline_sweeps(*, max_rows: int | None) -> int:
    """Keep running full sweeps until one pass finds no eligible rows."""
    started_at = time.monotonic()
    pass_number = 0
    while True:
        pass_number += 1
        print(
            f"Pipeline drain pass={pass_number} max_rows={max_rows}",
            flush=True,
        )
        result = await _run_one_pass(max_rows=max_rows)
        if result.skipped:
            print(
                f"Pipeline sweep skipped: {result.skip_reason} "
                f"elapsed_seconds={result.elapsed_seconds:.2f}",
                flush=True,
            )
            return 0
        if pipeline_pass_is_idle(result):
            elapsed_seconds = time.monotonic() - started_at
            print(
                f"Pipeline drain complete passes={pass_number} "
                f"elapsed_seconds={elapsed_seconds:.2f}",
                flush=True,
            )
            return 0
        print(
            f"Pipeline drain pass={pass_number} still had work; running another pass",
            flush=True,
        )


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv)
    if args.limit is not None and args.limit < 1:
        print("error: --limit must be >= 1", file=sys.stderr)
        return 2

    if args.drain and args.once:
        print("error: --drain and --once cannot be used together", file=sys.stderr)
        return 2

    drain = not args.once

    if args.enqueue or settings.pipeline_role == "api":
        if not args.enqueue and settings.pipeline_role == "api":
            print(
                "error: refusing to run a sweep inside the reloading backend process. "
                "Use docker compose exec pipeline-worker python -m "
                "app.core.scripts.run_pipeline_sweep_cli "
                "or pass --enqueue so pipeline-worker picks it up.",
                file=sys.stderr,
            )
            return 2
        with SessionLocal() as db:
            job_id = enqueue_pipeline_sweep(
                db,
                max_rows=args.limit,
                use_advisory_lock=True,
            )
        print(f"Pipeline sweep enqueued job_id={job_id} max_rows={args.limit}", flush=True)
        if drain:
            print(
                "note: enqueued jobs are drained automatically by pipeline-worker "
                "until the backlog is idle.",
                flush=True,
            )
        return 0

    if drain:
        print(f"Pipeline sweep CLI draining max_rows={args.limit}", flush=True)
        return asyncio.run(drain_pipeline_sweeps(max_rows=args.limit))

    print(f"Pipeline sweep CLI starting max_rows={args.limit}", flush=True)
    result: PipelineSweepResult = asyncio.run(_run_one_pass(max_rows=args.limit))
    if result.skipped:
        print(
            f"Pipeline sweep skipped: {result.skip_reason} "
            f"elapsed_seconds={result.elapsed_seconds:.2f}",
            flush=True,
        )
        return 0

    print(
        f"Pipeline sweep completed elapsed_seconds={result.elapsed_seconds:.2f}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
