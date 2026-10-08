"""Reconcile due summary bulletins (one pass; the compose service loops)."""

from __future__ import annotations

import logging

from app.core.database import SessionLocal
from app.core.logging_config import configure_logging
from app.news.services.summaries.reconcile_worker import run_reconcile_batch

logger = logging.getLogger(__name__)
SWEEP_NAME = "summary_reconcile_sweep"


def main() -> int:
    configure_logging()
    try:
        summary = run_reconcile_batch(SessionLocal)
    except Exception:
        logger.exception("Summary reconcile sweep failed")
        return 1

    line = (
        f"Summary reconcile mode={summary['mode']} processed={summary['processed']} "
        f"succeeded={summary['succeeded']} failed={summary['failed']} skipped={summary['skipped']}"
    )
    logger.info("%s sweep_name=%s", line, SWEEP_NAME)
    print(line, flush=True)
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
