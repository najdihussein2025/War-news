from datetime import datetime, time, timedelta, timezone
from uuid import UUID
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from app.logs.dtos.audit_log_dto import AuditLogFilterData, AuditLogItemDTO, AuditLogPageDTO
from app.logs.models import AuditLog

class AuditLogRepository:
    def __init__(self, db: Session) -> None: self.db = db

    def record(self, *, action: str, target_type: str, target_id: str, actor_id: UUID | None, actor_name: str, client_ip: str | None, old_values: dict | None = None, new_values: dict | None = None) -> None:
        self.db.add(AuditLog(action=action, target_type=target_type, target_id=target_id, actor_id=actor_id, actor_name=actor_name, client_ip=client_ip, old_values=old_values, new_values=new_values))
        self.db.commit()

    def list_page(self, filters: AuditLogFilterData) -> AuditLogPageDTO:
        conditions = []
        if filters.search:
            pattern = f"%{filters.search.strip()}%"
            conditions.append(or_(AuditLog.action.ilike(pattern), AuditLog.actor_name.ilike(pattern), AuditLog.target_id.ilike(pattern), AuditLog.target_type.ilike(pattern)))
        if filters.action: conditions.append(AuditLog.action == filters.action)
        if filters.date_from: conditions.append(AuditLog.created_at >= datetime.combine(filters.date_from, time.min, tzinfo=timezone.utc))
        if filters.date_to: conditions.append(AuditLog.created_at < datetime.combine(filters.date_to + timedelta(days=1), time.min, tzinfo=timezone.utc))
        total = self.db.scalar(select(func.count()).select_from(AuditLog).where(*conditions)) or 0
        rows = self.db.scalars(select(AuditLog).where(*conditions).order_by(AuditLog.created_at.desc()).offset((filters.page - 1) * filters.page_size).limit(filters.page_size)).all()
        return AuditLogPageDTO(items=[AuditLogItemDTO(id=x.id, action=x.action, performed_by=x.actor_name, actor_id=x.actor_id, target_type=x.target_type, target=x.target_id, ip=str(x.client_ip) if x.client_ip else None, old_values=x.old_values, new_values=x.new_values, timestamp=x.created_at) for x in rows], total=total, page=filters.page, page_size=filters.page_size)
