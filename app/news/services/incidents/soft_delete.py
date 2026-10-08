"""Single audited deletion boundary for incidents."""
from __future__ import annotations

from uuid import UUID

from app.news.models import Incident, UpdateAction
from app.news.services.incidents.incident_change_log import record_incident_change


def soft_delete_incident(db, incident: Incident, *, reason: str, canonical_incident_id: UUID | None = None, performed_by: UUID | None = None) -> None:
    """Soft-delete only with a durable reason and an incident_updates audit row."""
    if not reason:
        raise ValueError("soft-delete requires a reason")
    if incident.is_deleted:
        return
    incident.is_deleted = True
    incident.deleted_reason = reason
    incident.duplicate_flag = False
    record_incident_change(db, incident_id=incident.id, action=UpdateAction.delete,
        old_values={"is_deleted": False}, new_values={"is_deleted": True, "deleted_reason": reason, "canonical_incident_id": canonical_incident_id}, performed_by=performed_by)
    db.add(incident)
