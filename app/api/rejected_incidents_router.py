"""Admin review surface for soft-deleted, summary-audit incidents."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.api.deps import require_admin
from app.core.database import get_db
from app.news.models import Condition, Incident, UpdateAction, Village
from app.news.services.incidents.incident_change_log import record_incident_change
from app.news.services.summaries.decision_reasons import append_note

router = APIRouter(prefix="/api/rejected-incidents", tags=["rejected-incidents"])


@router.get("")
def list_rejected_incidents(reason: str | None = None, channel: str | None = None, date_from: str | None = None, date_to: str | None = None, limit: int = Query(100, ge=1, le=150), offset: int = Query(0, ge=0), _user: User = Depends(require_admin), db: Session = Depends(get_db)):
    query = select(Incident, Village.ref_name_ar, Condition.action_ar).outerjoin(Village).outerjoin(Condition).where(Incident.is_deleted.is_(True), Incident.decision_reason.is_not(None))
    if reason: query = query.where(Incident.decision_reason == reason)
    if date_from: query = query.where(Incident.event_date >= date_from)
    if date_to: query = query.where(Incident.event_date <= date_to)
    # Channel is intentionally deferred until source-summary joins land in 0078 data.
    rows = db.execute(query.order_by(Incident.decided_at.desc().nullslast()).limit(limit).offset(offset)).all()
    total = db.scalar(select(func.count()).select_from(Incident).where(Incident.is_deleted.is_(True), Incident.decision_reason.is_not(None))) or 0
    return {"items": [{"id": str(i.id), "village": village, "condition": condition, "event_date": i.event_date, "source_name": i.source_id, "decision_reason": i.decision_reason, "decision_ref_incident_id": str(i.decision_ref_incident_id) if i.decision_ref_incident_id else None, "note": i.note} for i, village, condition in rows], "total": total}


@router.post("/{incident_id}/restore")
def restore_rejected_incident(incident_id: UUID, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    incident = db.scalar(select(Incident).where(Incident.id == incident_id, Incident.is_deleted.is_(True), Incident.decision_reason.is_not(None)).with_for_update())
    if incident is None: raise HTTPException(404, "Rejected incident not found")
    old_reason = incident.decision_reason
    incident.is_deleted = False; incident.deleted_reason = None; incident.decision_reason = None
    incident.note = append_note(incident.note, f"أعيد بواسطة {user.email} بتاريخ {datetime.now(timezone.utc).date().isoformat()}.")
    record_incident_change(db, incident_id=incident.id, action=UpdateAction.status_change, old_values={"is_deleted": True, "decision_reason": old_reason}, new_values={"is_deleted": False, "decision_reason": None}, performed_by=user.id)
    db.commit()
    return {"id": str(incident.id), "restored": True}
