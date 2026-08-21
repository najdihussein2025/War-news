from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.sources.dtos import (
    SourceDetailDTO,
    SourceListItemDTO,
)
from app.sources.interfaces import SourceRepositoryInterface
from app.logs.models import IngestionLog
from app.news.models import RawMessage
from app.sources.models import ContentSourceBlock, Source, SourcePlatform


class SourceRepository(SourceRepositoryInterface):
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(self) -> list[SourceListItemDTO]:
        rows = self.db.execute(
            select(
                Source.id,
                Source.type,
                Source.name,
                Source.is_active,
                func.max(RawMessage.received_at).label("last_message_at"),
                func.count(RawMessage.id).label("total_messages"),
            )
            .outerjoin(RawMessage, RawMessage.source_id == Source.id)
            .group_by(Source.id, Source.type, Source.name, Source.is_active)
            .order_by(Source.id.asc())
        ).all()
        return [SourceListItemDTO.model_validate(row._mapping) for row in rows]

    def get_detail(self, source_id: int) -> SourceDetailDTO | None:
        row = self.db.execute(
            select(
                Source.id,
                Source.type,
                Source.name,
                Source.is_active,
                Source.external_id,
                Source.created_at,
                Source.last_cursor,
                func.max(RawMessage.received_at).label("last_message_at"),
                func.count(RawMessage.id).label("total_messages"),
            )
            .outerjoin(RawMessage, RawMessage.source_id == Source.id)
            .where(Source.id == source_id)
            .group_by(
                Source.id,
                Source.type,
                Source.name,
                Source.is_active,
                Source.external_id,
                Source.created_at,
                Source.last_cursor,
            )
        ).one_or_none()
        if row is None:
            return None
        return SourceDetailDTO.model_validate(row._mapping)

    def set_active(
        self,
        source_id: int,
        is_active: bool,
    ) -> SourceDetailDTO | None:
        source = self.get_by_id(source_id)
        if source is None:
            return None
        source.is_active = is_active
        self.db.add(source)
        self.db.commit()
        return self.get_detail(source_id)

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

    def get_or_create_source_platform_id(
        self,
        platform: str | None,
        name: str | None,
    ) -> int | None:
        if not platform or not name:
            return None

        existing_id = self.db.scalar(
            select(SourcePlatform.id).where(
                SourcePlatform.platform == platform,
                SourcePlatform.name == name,
            )
        )
        if existing_id is not None:
            return int(existing_id)

        with self.db.begin_nested():
            self.db.execute(
                insert(SourcePlatform)
                .values(platform=platform, name=name)
                .on_conflict_do_nothing(
                    index_elements=["platform", "name"],
                )
            )

        resolved_id = self.db.scalar(
            select(SourcePlatform.id).where(
                SourcePlatform.platform == platform,
                SourcePlatform.name == name,
            )
        )
        if resolved_id is None:
            raise RuntimeError(
                f"SourcePlatform ({platform!r}, {name!r}) could not be resolved."
            )
        return int(resolved_id)

    def is_content_source_blocked(
        self,
        source_platform: str | None,
        origin_account: str | None,
    ) -> bool:
        if not source_platform or not origin_account:
            return False

        return bool(
            self.db.scalar(
                select(ContentSourceBlock.is_blocked).where(
                    ContentSourceBlock.source_platform == source_platform,
                    ContentSourceBlock.origin_account == origin_account,
                    ContentSourceBlock.is_blocked.is_(True),
                )
            )
        )

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
        messages_blocked: int = 0,
        messages_flagged: int = 0,
        source_platforms: list[str] | None = None,
        platform_breakdown: dict[str, dict[str, int]] | None = None,
    ) -> None:
        self.db.rollback()
        self.db.add(
            IngestionLog(
                source_id=source_id,
                source_platforms=sorted({platform.lower() for platform in source_platforms or [] if platform}),
                platform_breakdown=platform_breakdown or {},
                messages_fetched=messages_fetched,
                messages_parsed=messages_parsed,
                messages_flagged=messages_flagged,
                messages_failed=messages_failed,
                messages_blocked=messages_blocked,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
            )
        )
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()
