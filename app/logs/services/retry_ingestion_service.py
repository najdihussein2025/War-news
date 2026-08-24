import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.logs.models import IngestionLog
from app.sources.actions import IngestSourceAction
from app.sources.dtos import IngestSourceData
from app.sources.repositories import SourceRepository

logger = logging.getLogger(__name__)


class RetryTrackingSourceRepository(SourceRepository):
    def __init__(self, db: Session, log_id: int) -> None:
        super().__init__(db)
        self.log_id = log_id

    def write_ingestion_log(
        self,
        source_id: int,
        messages_fetched: int,
        messages_parsed: int,
        messages_failed: int,
        started_at: datetime,
        messages_blocked: int = 0,
        messages_flagged: int = 0,
        source_platforms: list[str] | None = None,
        platform_breakdown: dict[str, dict[str, int]] | None = None,
    ) -> None:
        self.db.rollback()
        row = self.db.get(IngestionLog, self.log_id)
        if row is None:
            return
        row.messages_fetched = messages_fetched
        row.messages_parsed = messages_parsed
        row.messages_failed = messages_failed
        row.messages_blocked = messages_blocked
        row.messages_flagged = messages_flagged
        row.source_platforms = sorted({platform.lower() for platform in source_platforms or [] if platform})
        row.platform_breakdown = platform_breakdown or {}
        row.started_at = started_at
        row.finished_at = datetime.now(timezone.utc)
        row.status = "completed"
        self.db.commit()


def run_ingestion_retry(source_id: int, log_id: int) -> None:
    db = SessionLocal()
    try:
        IngestSourceAction(RetryTrackingSourceRepository(db, log_id)).execute(
            IngestSourceData(
                source_id=source_id,
                page_limit=2000,
                max_batches=10,
                min_message_datetime=datetime.now(timezone.utc) - timedelta(hours=24),
            )
        )
    except Exception as exc:
        db.rollback()
        row = db.get(IngestionLog, log_id)
        if row is not None:
            row.status = "failed"
            row.error_message = str(exc)[:2000]
            row.finished_at = datetime.now(timezone.utc)
            db.commit()
        logger.exception("Retried ingestion failed for source_id=%s", source_id)
    finally:
        db.close()
