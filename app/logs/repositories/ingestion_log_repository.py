from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.logs.dtos import IngestionLogFilterData, IngestionLogItemDTO, IngestionLogPageDTO
from app.logs.interfaces import IngestionLogRepositoryInterface
from app.logs.models import IngestionLog
from app.sources.models import Source


class IngestionLogRepository(IngestionLogRepositoryInterface):
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _to_dto(row: IngestionLog) -> IngestionLogItemDTO:
        duration = None
        if row.started_at and row.finished_at:
            duration = max(0, int((row.finished_at - row.started_at).total_seconds()))
        return IngestionLogItemDTO(
            id=row.id,
            source_id=row.source_id,
            source_name=row.source.name,
            source_platforms=row.source_platforms,
            platform_breakdown=row.platform_breakdown,
            run_timestamp=row.started_at or row.created_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
            duration_seconds=duration,
            messages_fetched=row.messages_fetched,
            messages_parsed=row.messages_parsed,
            messages_flagged=row.messages_flagged,
            messages_failed=row.messages_failed,
            messages_blocked=row.messages_blocked,
            status=row.status,
            error_message=row.error_message,
            retry_of_id=row.retry_of_id,
        )

    def list_page(self, filters: IngestionLogFilterData) -> IngestionLogPageDTO:
        conditions = [
            or_(
                Source.external_id.is_(None),
                Source.external_id != "red_alert_telegram",
                IngestionLog.messages_parsed > 0,
            )
        ]
        if filters.source_id is not None:
            conditions.append(IngestionLog.source_id == filters.source_id)
        if filters.status:
            conditions.append(IngestionLog.status == filters.status)
        if filters.date_from:
            conditions.append(IngestionLog.created_at >= datetime.combine(filters.date_from, time.min, tzinfo=timezone.utc))
        if filters.date_to:
            conditions.append(IngestionLog.created_at < datetime.combine(filters.date_to + timedelta(days=1), time.min, tzinfo=timezone.utc))
        total = self.db.scalar(
            select(func.count())
            .select_from(IngestionLog)
            .join(Source, Source.id == IngestionLog.source_id)
            .where(*conditions)
        ) or 0
        rows = self.db.scalars(
            select(IngestionLog)
            .join(Source, Source.id == IngestionLog.source_id)
            .options(joinedload(IngestionLog.source))
            .where(*conditions)
            .order_by(IngestionLog.created_at.desc())
            .offset((filters.page - 1) * filters.page_size)
            .limit(filters.page_size)
        ).all()
        return IngestionLogPageDTO(items=[self._to_dto(row) for row in rows], total=total, page=filters.page, page_size=filters.page_size)

    def get(self, log_id: int) -> IngestionLogItemDTO | None:
        row = self.db.scalar(select(IngestionLog).options(joinedload(IngestionLog.source)).where(IngestionLog.id == log_id))
        return self._to_dto(row) if row else None

    def start_retry(self, original_log_id: int) -> IngestionLogItemDTO | None:
        original = self.db.scalar(select(IngestionLog).options(joinedload(IngestionLog.source)).where(IngestionLog.id == original_log_id))
        if original is None or original.status != "failed":
            return None
        row = IngestionLog(source_id=original.source_id, source_platforms=original.source_platforms, platform_breakdown=original.platform_breakdown, status="running", retry_of_id=original.id, started_at=datetime.now(timezone.utc))
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        row.source = original.source
        return self._to_dto(row)
