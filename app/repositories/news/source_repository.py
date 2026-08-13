from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.interfaces.repositories import SourceRepositoryInterface
from app.models.news import IngestionLog, RawMessage, Source


class SourceRepository(SourceRepositoryInterface):
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(self) -> list[Source]:
        return list(self.db.scalars(select(Source).order_by(Source.id.asc())).all())

    def get_by_id(self, source_id: int) -> Source | None:
        return self.db.get(Source, source_id)

    def get_active_by_external_id(self, external_id: str) -> Source | None:
        return self.db.scalar(
            select(Source).where(
                Source.external_id == external_id,
                Source.is_active.is_(True),
            )
        )

    def add_raw_message(self, raw_message: RawMessage) -> None:
        with self.db.begin_nested():
            self.db.add(raw_message)
            self.db.flush()

    def commit(self) -> None:
        self.db.commit()

    def is_duplicate_raw_message_error(self, exc: IntegrityError) -> bool:
        constraint_name = getattr(
            getattr(exc.orig, "diag", None),
            "constraint_name",
            None,
        )
        return (
            constraint_name == "uq_raw_messages_source_external_message"
            or "uq_raw_messages_source_external_message" in str(exc.orig)
        )

    def update_last_cursor(self, source: Source, cursor: str | None) -> None:
        source.last_cursor = cursor
        self.db.add(source)
        self.db.commit()

    def write_ingestion_log(
        self,
        source_id: int,
        messages_fetched: int,
        messages_parsed: int,
        messages_failed: int,
        started_at: datetime,
    ) -> None:
        self.db.rollback()
        self.db.add(
            IngestionLog(
                source_id=source_id,
                messages_fetched=messages_fetched,
                messages_parsed=messages_parsed,
                messages_flagged=0,
                messages_failed=messages_failed,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
            )
        )
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()
