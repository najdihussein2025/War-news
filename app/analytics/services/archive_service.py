"""Snapshot ``incidents`` into ``incidents_archive`` before the data reset."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.models.incident_archive import ARCHIVE_DETAIL_COLUMNS, ARCHIVE_INCIDENT_COLUMNS

STATUS_COUNTS_SQL = """
SELECT verification_status, is_deleted, count(*) AS rows,
       coalesce(sum(coalesce(total_deaths, 0)), 0) AS deaths,
       coalesce(sum(coalesce(total_injuries, 0)), 0) AS injuries
FROM {table}
{where}
GROUP BY verification_status, is_deleted
ORDER BY verification_status, is_deleted
"""


class ArchiveError(RuntimeError):
    pass


def batch_exists(db: Session, batch: str) -> bool:
    return bool(db.execute(
        text("SELECT 1 FROM incidents_archive WHERE archive_batch = :batch LIMIT 1"), {"batch": batch}
    ).first())


def live_status_counts(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(text(STATUS_COUNTS_SQL.format(table="incidents", where="")))
    return [dict(row._mapping) for row in rows]


def archive_status_counts(db: Session, batch: str) -> list[dict[str, Any]]:
    rows = db.execute(
        text(STATUS_COUNTS_SQL.format(table="incidents_archive", where="WHERE archive_batch = :batch")),
        {"batch": batch},
    )
    return [dict(row._mapping) for row in rows]


def _insert_sql() -> str:
    incident_columns = [c for c in ARCHIVE_INCIDENT_COLUMNS]
    target = ", ".join(
        ["archive_batch", "archived_at", *incident_columns, *ARCHIVE_DETAIL_COLUMNS,
         "bulletin_casualty_group_id", "casualty_scope"]
    )
    source = ", ".join(
        [":batch", "now()"]
        + [("i.origin::text" if c == "origin" else f"i.{c}") for c in incident_columns]
        + [f"d.{c}" for c in ARCHIVE_DETAIL_COLUMNS]
        + ["g.group_id", "g.casualty_scope"]
    )
    return f"""
        INSERT INTO incidents_archive ({target})
        SELECT {source}
        FROM incidents i
        LEFT JOIN incident_details d ON d.incident_id = i.id
        LEFT JOIN LATERAL (
            SELECT m.group_id, bg.casualty_scope::text AS casualty_scope
            FROM bulletin_casualty_group_members m
            JOIN bulletin_casualty_groups bg ON bg.id = m.group_id
            WHERE m.incident_id = i.id
            ORDER BY m.group_id
            LIMIT 1
        ) g ON true
    """


def archive_incidents(db: Session, batch: str) -> dict[str, Any]:
    """Copy every incident (deleted ones included) into the archive, in the caller's transaction.

    Raises ``ArchiveError`` (leaving the caller to roll back) when the batch exists
    or the archived counts do not equal the live counts.
    """
    if batch_exists(db, batch):
        raise ArchiveError(f"archive batch {batch!r} already exists; refusing to overwrite it")
    before = live_status_counts(db)
    db.execute(text(_insert_sql()), {"batch": batch})
    after = archive_status_counts(db, batch)
    if _comparable(before) != _comparable(after):
        raise ArchiveError(
            f"archive counts do not match the live table: live={before} archive={after}"
        )
    return {"live": before, "archive": after, "rows": sum(r["rows"] for r in after)}


def _comparable(rows: list[dict[str, Any]]) -> list[tuple]:
    return sorted(
        (r["verification_status"], bool(r["is_deleted"]), int(r["rows"]), int(r["deaths"]), int(r["injuries"]))
        for r in rows
    )
