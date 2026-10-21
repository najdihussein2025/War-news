"""Copy all incidents into incidents_archive (history before the data reset).

Dry-run by default; writes only with --apply. Refuses a batch name that exists.

    python -m scripts.analytics_archive_incidents --batch pre_reset_2026_10
    python -m scripts.analytics_archive_incidents --batch pre_reset_2026_10 --apply
"""

from __future__ import annotations

import argparse
import logging

from app.analytics.services.archive_service import (
    ArchiveError,
    archive_incidents,
    batch_exists,
    live_status_counts,
)
from app.core.database import SessionLocal
from app.core.logging_config import configure_logging

logger = logging.getLogger(__name__)
SWEEP_NAME = "analytics_archive_incidents"


def _print_counts(title: str, rows: list[dict]) -> None:
    print(title)
    print(f"  {'verification_status':<20} {'is_deleted':<11} {'rows':>7} {'deaths':>7} {'injuries':>9}")
    for row in rows:
        print(
            f"  {row['verification_status']:<20} {str(bool(row['is_deleted'])).lower():<11} "
            f"{row['rows']:>7} {row['deaths']:>7} {row['injuries']:>9}"
        )
    print(f"  total rows: {sum(r['rows'] for r in rows)}")


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True, help="archive batch name, e.g. pre_reset_2026_10")
    parser.add_argument("--apply", action="store_true", help="write the archive (default is dry-run)")
    args = parser.parse_args()

    processed = succeeded = failed = 0
    try:
        with SessionLocal() as db:
            if batch_exists(db, args.batch):
                print(f"batch {args.batch!r} already exists; refusing.")
                failed = 1
            else:
                live = live_status_counts(db)
                _print_counts("incidents that would be copied (the recon reported 3,570 total):", live)
                processed = sum(r["rows"] for r in live)
                if args.apply:
                    try:
                        result = archive_incidents(db, args.batch)
                        db.commit()
                    except ArchiveError as exc:
                        db.rollback()
                        print(f"ARCHIVE FAILED, rolled back: {exc}")
                        failed = processed
                    else:
                        _print_counts("archived (verified equal to live):", result["archive"])
                        succeeded = result["rows"]
                else:
                    print("dry-run: nothing written (use --apply).")
                    succeeded = processed
    except Exception:
        logger.exception("analytics archive failed")
        return 1

    line = f"Analytics archive processed={processed} succeeded={succeeded} failed={failed}"
    logger.info("%s sweep_name=%s", line, SWEEP_NAME)
    print(line, flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
