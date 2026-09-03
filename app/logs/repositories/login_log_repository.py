from datetime import datetime, time, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.logs.dtos import LoginLogFilterData, LoginLogItemDTO, LoginLogPageDTO
from app.logs.interfaces import LoginLogRepositoryInterface
from app.logs.models import LoginLog


class LoginLogRepository(LoginLogRepositoryInterface):
    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        *,
        username: str,
        success: bool,
        client_ip: str,
        user_id: UUID | None = None,
        failure_reason: str | None = None,
    ) -> None:
        self.db.add(
            LoginLog(
                username=username.strip(),
                success=success,
                client_ip=client_ip,
                user_id=user_id,
                failure_reason=failure_reason,
            )
        )
        self.db.commit()

    def list_page(self, filters: LoginLogFilterData) -> LoginLogPageDTO:
        conditions = []
        if filters.search:
            pattern = f"%{filters.search.strip()}%"
            conditions.append(
                or_(LoginLog.username.ilike(pattern), LoginLog.client_ip.ilike(pattern))
            )
        if filters.success is not None:
            conditions.append(LoginLog.success.is_(filters.success))
        if filters.date_from:
            conditions.append(
                LoginLog.created_at
                >= datetime.combine(filters.date_from, time.min, tzinfo=timezone.utc)
            )
        if filters.created_after:
            conditions.append(LoginLog.created_at >= filters.created_after)
        if filters.date_to:
            conditions.append(
                LoginLog.created_at
                < datetime.combine(filters.date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
            )

        filtered = select(LoginLog).where(*conditions)
        total = self.db.scalar(
            select(func.count()).select_from(LoginLog).where(*conditions)
        ) or 0
        rows = self.db.scalars(
            filtered.order_by(LoginLog.created_at.desc())
            .offset((filters.page - 1) * filters.page_size)
            .limit(filters.page_size)
        ).all()
        return LoginLogPageDTO(
            items=[
                LoginLogItemDTO(
                    id=row.id,
                    username=row.username,
                    success=row.success,
                    ip=row.client_ip,
                    timestamp=row.created_at,
                )
                for row in rows
            ],
            total=total,
            page=filters.page,
            page_size=filters.page_size,
        )
