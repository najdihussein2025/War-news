from abc import ABC, abstractmethod
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.sources.dtos import (
    SourceDetailDTO,
    SourceListItemDTO,
)
from app.news.models import RawMessage
from app.sources.models import Source


class SourceRepositoryInterface(ABC):
    @abstractmethod
    def list_all(self) -> list[SourceListItemDTO]:
        pass

    @abstractmethod
    def get_detail(self, source_id: int) -> SourceDetailDTO | None:
        pass

    @abstractmethod
    def set_active(
        self,
        source_id: int,
        is_active: bool,
    ) -> SourceDetailDTO | None:
        pass

    @abstractmethod
    def get_by_id(self, source_id: int) -> Source | None:
        pass

    @abstractmethod
    def get_active_by_external_id(self, external_id: str) -> Source | None:
        pass

    @abstractmethod
    def add_raw_message(self, raw_message: RawMessage) -> None:
        pass

    @abstractmethod
    def commit(self) -> None:
        pass

    @abstractmethod
    def is_duplicate_raw_message_error(self, exc: IntegrityError) -> bool:
        pass

    @abstractmethod
    def update_last_cursor(self, source: Source, cursor: str | None) -> None:
        pass

    @abstractmethod
    def write_ingestion_log(
        self,
        source_id: int,
        messages_fetched: int,
        messages_parsed: int,
        messages_failed: int,
        started_at: datetime,
    ) -> None:
        pass

    @abstractmethod
    def rollback(self) -> None:
        pass
