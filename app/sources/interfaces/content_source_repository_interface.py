from abc import ABC, abstractmethod
from uuid import UUID

from app.sources.dtos import (
    ContentSourceBlockDTO,
    ContentSourceDetailDTO,
    ContentSourceFilterData,
    ContentSourceListItemDTO,
)


class ContentSourceRepositoryInterface(ABC):
    @abstractmethod
    def list_all(
        self,
        filters: ContentSourceFilterData,
    ) -> list[ContentSourceListItemDTO]:
        pass

    @abstractmethod
    def get_detail(
        self,
        source_platform: str,
        origin_account: str,
    ) -> ContentSourceDetailDTO | None:
        pass

    @abstractmethod
    def set_blocked(
        self,
        source_platform: str,
        origin_account: str,
        is_blocked: bool,
        blocked_by: UUID | None = None,
    ) -> ContentSourceBlockDTO:
        pass

    @abstractmethod
    def is_blocked(self, source_platform: str | None, origin_account: str | None) -> bool:
        pass
