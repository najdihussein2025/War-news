"""Reconcile open multi-village bulletin casualty groups."""

from __future__ import annotations

import logging

from app.core.database import SessionLocal
from app.core.logging_config import configure_logging
from app.news.services.reconciliation import BulletinReconciliationService

logger = logging.getLogger(__name__)
SWEEP_NAME = "bulletin_reconciliation_sweep"


def main() -> int:
    configure_logging()
    try:
        with SessionLocal() as db:
            summary = BulletinReconciliationService(db).run_once()
    except Exception:
        logger.exception("Bulletin reconciliation sweep failed")
        return 1

    line = (
        f"Bulletin reconciliation processed={summary['processed']} "
        f"succeeded={summary['succeeded']} failed={summary['failed']} "
        f"expired={summary['expired']} resolved={summary['resolved']} "
        f"pending={summary['pending']}"
    )
    logger.info("%s sweep_name=%s", line, SWEEP_NAME)
    print(line, flush=True)
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
