"""Single writer for incident_updates audit rows.

Every incident mutation path (admin edit/delete/create/restore and pipeline
soft-deletes) records its change through ``record_incident_change`` so the
audit trail has one shape.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy.orm import Session

from app.news.models import IncidentUpdate, UpdateAction


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def _json_values(values: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if values is None:
        return None
    return {key: _json_value(value) for key, value in values.items()}


def changed_fields(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (old, new) restricted to keys whose value actually changed."""
    keys = [key for key in after if before.get(key) != after.get(key)]
    return (
        {key: before.get(key) for key in keys},
        {key: after.get(key) for key in keys},
    )


def record_incident_change(
    db: Session,
    *,
    incident_id: UUID | str,
    action: UpdateAction,
    old_values: Mapping[str, Any] | None,
    new_values: Mapping[str, Any] | None,
    performed_by: UUID | None,
) -> IncidentUpdate:
    """Add (not commit) one audit row; the caller commits with its change."""
    entry = IncidentUpdate(
        incident_id=incident_id,
        action=action,
        old_values=_json_values(old_values),
        new_values=_json_values(new_values),
        performed_by=performed_by,
    )
    db.add(entry)
    return entry
