from __future__ import annotations

import argparse
import asyncio
import sys

from app.core.logging_config import configure_logging
from app.news.dtos.pipeline_dto import PipelineSweepResult, StageSweepResult
from app.news.services.pipeline_orchestrator import run_full_pipeline_sweep


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
            "Run the full news pipeline sweep in a standalone process, "
            "outside uvicorn --reload."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Optional cap on eligible rows processed per stage (same as ?limit=).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv)
    if args.limit is not None and args.limit < 1:
        print("error: --limit must be >= 1", file=sys.stderr)
        return 2

    print(f"Pipeline sweep CLI starting max_rows={args.limit}", flush=True)
    result: PipelineSweepResult = asyncio.run(
        run_full_pipeline_sweep(max_rows=args.limit, on_stage=_print_stage)
    )
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
