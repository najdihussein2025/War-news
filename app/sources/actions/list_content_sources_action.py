from app.sources.dtos import (
    ContentSourceFilterData,
    ContentSourceListItemDTO,
)
from app.sources.interfaces import ContentSourceRepositoryInterface


class ListContentSourcesAction:
    def __init__(self, content_sources: ContentSourceRepositoryInterface) -> None:
        self.content_sources = content_sources

    def execute(
        self,
        filters: ContentSourceFilterData,
    ) -> list[ContentSourceListItemDTO]:
        return self.content_sources.list_all(filters)
