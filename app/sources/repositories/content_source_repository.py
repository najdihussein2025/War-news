from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.sources.dtos import (
    ContentSourceBlockDTO,
    ContentSourceDetailDTO,
    ContentSourceFilterData,
    ContentSourceListItemDTO,
    ContentSourceRecentMessageDTO,
)
from app.sources.interfaces import ContentSourceRepositoryInterface
from app.news.models import RawMessage
from app.sources.models import ContentSourceBlock


GENERIC_CONTENT_SOURCE_NAME = "CNRS Webhook"


class ContentSourceRepository(ContentSourceRepositoryInterface):
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(
        self,
        filters: ContentSourceFilterData,
    ) -> list[ContentSourceListItemDTO]:
        origin_account = func.coalesce(RawMessage.origin_account, RawMessage.source_name)
        query = (
            select(
                RawMessage.source_platform,
                RawMessage.source_name,
                origin_account.label("origin_account"),
                func.count(RawMessage.id).label("message_count"),
                func.max(
                    func.coalesce(RawMessage.message_datetime, RawMessage.received_at)
                ).label("last_seen"),
                func.min(RawMessage.received_at).label("first_seen"),
                func.coalesce(ContentSourceBlock.is_blocked, False).label("is_blocked"),
            )
            .outerjoin(
                ContentSourceBlock,
                (ContentSourceBlock.source_platform == RawMessage.source_platform)
                & (ContentSourceBlock.origin_account == origin_account),
            )
            .where(
                RawMessage.source_platform.is_not(None),
                RawMessage.source_name.is_not(None),
                RawMessage.source_name != GENERIC_CONTENT_SOURCE_NAME,
            )
            .group_by(RawMessage.source_platform, RawMessage.source_name)
            .group_by(origin_account, ContentSourceBlock.is_blocked)
            .order_by(func.count(RawMessage.id).desc(), RawMessage.source_name.asc())
        )

        if filters.platform:
            query = query.where(RawMessage.source_platform == filters.platform)

        if filters.search:
            query = query.where(RawMessage.source_name.ilike(f"%{filters.search}%"))

        rows = self.db.execute(query).all()
        return [ContentSourceListItemDTO.model_validate(row._mapping) for row in rows]

    def get_detail(
        self,
        source_platform: str,
        origin_account: str,
    ) -> ContentSourceDetailDTO | None:
        account = func.coalesce(RawMessage.origin_account, RawMessage.source_name)
        summary = self.db.execute(
            select(
                RawMessage.source_platform,
                func.max(RawMessage.source_name).label("source_name"),
                account.label("origin_account"),
                func.count(RawMessage.id).label("message_count"),
                func.max(
                    func.coalesce(RawMessage.message_datetime, RawMessage.received_at)
                ).label("last_seen"),
                func.min(RawMessage.received_at).label("first_seen"),
                func.coalesce(ContentSourceBlock.is_blocked, False).label("is_blocked"),
            )
            .outerjoin(
                ContentSourceBlock,
                (ContentSourceBlock.source_platform == RawMessage.source_platform)
                & (ContentSourceBlock.origin_account == account),
            )
            .where(
                RawMessage.source_platform == source_platform,
                account == origin_account,
                RawMessage.source_name.is_not(None),
                RawMessage.source_name != GENERIC_CONTENT_SOURCE_NAME,
            )
            .group_by(RawMessage.source_platform, account, ContentSourceBlock.is_blocked)
        ).one_or_none()
        if summary is None:
            return None

        messages = self.db.execute(
            select(
                RawMessage.id,
                RawMessage.raw_text,
                RawMessage.message_datetime,
                RawMessage.received_at,
            )
            .where(
                RawMessage.source_platform == source_platform,
                account == origin_account,
                RawMessage.source_name != GENERIC_CONTENT_SOURCE_NAME,
            )
            .order_by(
                RawMessage.message_datetime.desc().nullslast(),
                RawMessage.received_at.desc(),
            )
            .limit(8)
        ).all()
        data = dict(summary._mapping)
        data["recent_messages"] = [
            ContentSourceRecentMessageDTO.model_validate(row._mapping)
            for row in messages
        ]
        return ContentSourceDetailDTO.model_validate(data)

    def set_blocked(
        self,
        source_platform: str,
        origin_account: str,
        is_blocked: bool,
        blocked_by: UUID | None = None,
    ) -> ContentSourceBlockDTO:
        block = self.db.scalar(
            select(ContentSourceBlock).where(
                ContentSourceBlock.source_platform == source_platform,
                ContentSourceBlock.origin_account == origin_account,
            )
        )
        if block is None:
            block = ContentSourceBlock(
                source_platform=source_platform,
                origin_account=origin_account,
            )

        block.is_blocked = is_blocked
        block.blocked_at = datetime.now(timezone.utc) if is_blocked else None
        block.blocked_by = blocked_by if is_blocked else None
        self.db.add(block)
        self.db.commit()
        self.db.refresh(block)
        return ContentSourceBlockDTO.model_validate(block)

    def is_blocked(self, source_platform: str | None, origin_account: str | None) -> bool:
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
