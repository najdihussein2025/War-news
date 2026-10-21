"""Rebuild analytics facts.

Default: process the dirty-date queue (what the worker loops). Other modes:

    python -m scripts.analytics_refresh_sweep                  # dirty queue
    python -m scripts.analytics_refresh_sweep --full           # rebuild every live fact
    python -m scripts.analytics_refresh_sweep --archive-batch NAME           # dry-run
    python -m scripts.analytics_refresh_sweep --archive-batch NAME --apply   # write archive facts

Archive facts are frozen: they are written once and never rewritten.
"""

from __future__ import annotations

import argparse
import logging

import app.accounts.models  # noqa: F401  (mapper registry for the repositories used by the builders)
import app.logs.models  # noqa: F401
import app.news.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.analytics.services import refresh_service
from app.analytics.services.refresh_service import ArchiveFactsError, RefreshSummary
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging_config import configure_logging

logger = logging.getLogger(__name__)
SWEEP_NAME = "analytics_refresh_sweep"


def _archive_dry_run(db, batch: str) -> RefreshSummary:
    from sqlalchemy import text

    rows = db.execute(
        text("SELECT count(*) FROM incidents_archive WHERE archive_batch = :b"), {"b": batch}
    ).scalar_one()
    existing = db.execute(
        text("SELECT count(*) FROM analytics_incident_facts WHERE source = 'archive' AND archive_batch = :b"),
        {"b": batch},
    ).scalar_one()
    print(f"archive batch {batch!r}: {rows} archived incidents, {existing} existing archive fact rows")
    if existing:
        print("archive facts already exist for this batch; --apply would refuse.")
        return RefreshSummary(processed=1, failed=1)
    print("dry-run: nothing written (use --apply).")
    return RefreshSummary(processed=1, succeeded=1)


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="rebuild every live fact")
    parser.add_argument("--archive-batch", help="build frozen archive facts for this batch")
    parser.add_argument("--apply", action="store_true", help="required to write archive facts")
    args = parser.parse_args()

    try:
        with SessionLocal() as db:
            if args.archive_batch:
                if args.apply:
                    try:
                        result = refresh_service.build_archive_facts(db, args.archive_batch)
                        summary = RefreshSummary(processed=1, succeeded=1, details=result)
                    except ArchiveFactsError as exc:
                        db.rollback()
                        print(f"ARCHIVE FACTS REFUSED: {exc}")
                        summary = RefreshSummary(processed=1, failed=1)
                else:
                    summary = _archive_dry_run(db, args.archive_batch)
            elif args.full:
                summary = refresh_service.full_rebuild(db)
            else:
                summary = refresh_service.process_dirty_queue(db, settings.analytics_refresh_batch_size)
    except Exception:
        logger.exception("Analytics refresh sweep failed")
        return 1

    line = (
        f"Analytics refresh processed={summary.processed} succeeded={summary.succeeded} "
        f"failed={summary.failed}"
    )
    logger.info("%s sweep_name=%s details=%s", line, SWEEP_NAME, summary.details)
    print(line, flush=True)
    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
