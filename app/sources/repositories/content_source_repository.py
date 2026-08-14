from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.sources.dtos import (
    ContentSourceFilterData,
    ContentSourceListItemDTO,
)
from app.sources.interfaces import ContentSourceRepositoryInterface
from app.news.models import RawMessage


class ContentSourceRepository(ContentSourceRepositoryInterface):
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(
        self,
        filters: ContentSourceFilterData,
    ) -> list[ContentSourceListItemDTO]:
        query = (
            select(
                RawMessage.source_platform,
                RawMessage.source_name,
                func.count(RawMessage.id).label("message_count"),
                func.max(RawMessage.received_at).label("last_seen"),
            )
            .where(
                RawMessage.source_platform.is_not(None),
                RawMessage.source_name.is_not(None),
            )
            .group_by(RawMessage.source_platform, RawMessage.source_name)
            .order_by(func.count(RawMessage.id).desc(), RawMessage.source_name.asc())
        )

        if filters.platform:
            query = query.where(RawMessage.source_platform == filters.platform)

        if filters.search:
            query = query.where(RawMessage.source_name.ilike(f"%{filters.search}%"))

        rows = self.db.execute(query).all()
        return [ContentSourceListItemDTO.model_validate(row._mapping) for row in rows]
