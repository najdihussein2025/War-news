from abc import ABC, abstractmethod

from app.dtos.news import ContentSourceFilterData, ContentSourceListItemDTO


class ContentSourceRepositoryInterface(ABC):
    @abstractmethod
    def list_all(
        self,
        filters: ContentSourceFilterData,
    ) -> list[ContentSourceListItemDTO]:
        pass
