"""Rebuild analytics facts: dirty-date queue, full rebuild, one-time archive facts.

Archive-sourced fact rows (``source = 'archive'``) are frozen: nothing here ever
deletes or rewrites them. Every live rebuild is one transaction.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.services import air_breach_fact_builder, incident_fact_builder
from app.core import cache

logger = logging.getLogger(__name__)

CACHE_VERSION_KEY = "analytics:version"
KIND_INCIDENT = "incident"
KIND_AIR = "air"


class ArchiveFactsError(RuntimeError):
    pass


@dataclass
class RefreshSummary:
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    details: dict = field(default_factory=dict)


def bump_cache_version() -> None:
    cache.increment(CACHE_VERSION_KEY)


def refresh_incident_dates(db: Session, dates: Iterable[date] | None) -> dict:
    """Replace the live incident facts of ``dates`` (``None`` = all) from the live table."""
    deleted = incident_fact_builder.delete_live_facts(db, dates)
    inserted = incident_fact_builder.insert_live_facts(db, dates)
    return {"deleted": deleted, "inserted": inserted}


def refresh_air_dates(db: Session, dates: Iterable[date]) -> dict:
    ordered = sorted(set(dates))
    if not ordered:
        return {"breaches": 0, "fact_rows": 0}
    return air_breach_fact_builder.rebuild_air_facts(
        db, from_date=air_breach_fact_builder.affected_from_date(ordered)
    )


def refresh_dates(db: Session, kind: str, dates: Iterable[date]) -> dict:
    """Rebuild one kind of facts for ``dates`` in the caller's transaction (no commit)."""
    dates = list(dates)
    if kind == KIND_INCIDENT:
        return refresh_incident_dates(db, dates)
    if kind == KIND_AIR:
        return refresh_air_dates(db, dates)
    raise ValueError(f"unknown analytics kind {kind!r}")


_DELETE_MARKS = text("""
DELETE FROM analytics_dirty_dates d
USING (SELECT * FROM unnest(CAST(:kinds AS text[]), CAST(:dates AS date[]), CAST(:marks AS timestamptz[]))
       AS t(kind, event_date, marked_at)) t
WHERE d.kind = t.kind AND d.event_date = t.event_date AND d.marked_at = t.marked_at
""")


def process_dirty_queue(db: Session, batch_size: int) -> RefreshSummary:
    """Rebuild up to ``batch_size`` queued dates.

    A queued row is deleted only when its ``marked_at`` is unchanged since it was
    read, so a change that lands during the rebuild keeps its mark for the next pass.
    """
    summary = RefreshSummary()
    rows = db.execute(
        text("SELECT kind, event_date, marked_at FROM analytics_dirty_dates "
             "ORDER BY marked_at LIMIT :n"),
        {"n": batch_size},
    ).all()
    db.rollback()  # end the read transaction; each kind below is its own
    by_kind: dict[str, list[tuple[date, datetime]]] = {}
    for kind, event_date, marked_at in rows:
        by_kind.setdefault(kind, []).append((event_date, marked_at))

    changed = False
    for kind, entries in by_kind.items():
        summary.processed += len(entries)
        try:
            summary.details[kind] = refresh_dates(db, kind, [d for d, _m in entries])
            db.execute(_DELETE_MARKS, {
                "kinds": [kind] * len(entries),
                "dates": [d for d, _m in entries],
                "marks": [m for _d, m in entries],
            })
            db.commit()
            summary.succeeded += len(entries)
            changed = True
        except Exception:
            db.rollback()
            logger.exception("analytics refresh failed kind=%s dates=%s", kind, [d for d, _m in entries])
            summary.failed += len(entries)
    if changed:
        bump_cache_version()
    return summary


def full_rebuild(db: Session) -> RefreshSummary:
    """Rebuild every live fact (incident + air). Archive facts are untouched."""
    summary = RefreshSummary(processed=2)
    started = db.execute(text("SELECT clock_timestamp()")).scalar_one()
    try:
        summary.details["incident"] = refresh_incident_dates(db, None)
        summary.details["air"] = air_breach_fact_builder.rebuild_air_facts(db, from_date=None)
        db.execute(text("DELETE FROM analytics_dirty_dates WHERE marked_at <= :started"), {"started": started})
        db.commit()
        summary.succeeded = 2
        bump_cache_version()
    except Exception:
        db.rollback()
        logger.exception("analytics full rebuild failed")
        summary.failed = 2
    return summary


def build_archive_facts(db: Session, batch: str) -> dict:
    """One-time: write ``source='archive'`` facts for ``batch`` (refuses if they exist)."""
    exists_in_archive = db.execute(
        text("SELECT 1 FROM incidents_archive WHERE archive_batch = :b LIMIT 1"), {"b": batch}
    ).first()
    if not exists_in_archive:
        raise ArchiveFactsError(f"archive batch {batch!r} has no rows in incidents_archive")
    already = db.execute(
        text("SELECT 1 FROM analytics_incident_facts WHERE source = 'archive' AND archive_batch = :b LIMIT 1"),
        {"b": batch},
    ).first()
    if already:
        raise ArchiveFactsError(f"archive facts for batch {batch!r} already exist; they are frozen")
    inserted = incident_fact_builder.insert_archive_facts(db, batch)
    db.commit()
    bump_cache_version()
    return {"inserted": inserted}
