"""Periodic backlog relevance sweep.

The new-only live sweep (scripts.live_sweep_new_only) gates the relevance
filter behind a persisted cursor, so rows at or below the cursor that are
still status='pending' with filter_result IS NULL are never revisited by
the hot path. This script runs the same relevance-filter stage with an
unpatched session, so it scans the full pending backlog regardless of the
cursor. Rows it marks parsed are picked up by the live sweep's downstream
stages, which are not cutoff-gated.

Intended to run on a much slower cadence than the hot path (see the
backlog-relevance-worker service in docker-compose.yml).
"""

from __future__ import annotations

import asyncio
import logging

from app.core.database import SessionLocal
from app.core.logging_config import configure_logging
from app.news.dtos.pipeline_dto import StageSweepResult
from app.news.services.pipeline_sweep_stages import sweep_relevance_filter

logger = logging.getLogger(__name__)

SWEEP_NAME = "backlog_relevance_sweep"
MAX_ROWS: int | None = None


def _emit_result(result: StageSweepResult) -> None:
    if result.aborted:
        line = (
            f"Pipeline stage={result.stage} aborted processed={result.processed} "
            f"succeeded={result.succeeded} failed={result.failed} "
            f"unprocessed={result.unprocessed} "
            f"elapsed_seconds={result.elapsed_seconds:.2f}"
        )
    else:
        line = (
            f"Pipeline stage={result.stage} processed={result.processed} "
            f"succeeded={result.succeeded} failed={result.failed} "
            f"elapsed_seconds={result.elapsed_seconds:.2f}"
        )
    logger.info("%s sweep_name=%s", line, SWEEP_NAME)
    print(line, flush=True)


async def main() -> int:
    configure_logging()
    logger.info(
        "Starting backlog relevance sweep (no cutoff gate) sweep_name=%s",
        SWEEP_NAME,
    )

    try:
        with SessionLocal() as db:
            result = await sweep_relevance_filter(db, max_rows=MAX_ROWS)
    except Exception:
        logger.exception(
            "Backlog relevance sweep failed sweep_name=%s",
            SWEEP_NAME,
        )
        return 0

    _emit_result(result)
    logger.info(
        "Completed backlog relevance sweep sweep_name=%s processed=%s",
        SWEEP_NAME,
        result.processed,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
