from abc import ABC, abstractmethod
from typing import Any

from app.dtos.news import ExtractionResult, RelevanceClassificationResult
from app.models.news import MessageStatus, RawMessage


class RawMessageRepositoryInterface(ABC):
    @abstractmethod
    def get_pending_unfiltered_batch(
        self,
        limit: int,
    ) -> list[RawMessage]:
        pass

    @abstractmethod
    def get_pending_extraction_batch(
        self,
        limit: int,
    ) -> list[RawMessage]:
        pass

    @abstractmethod
    def save_filter_result(
        self,
        message: RawMessage,
        result: RelevanceClassificationResult,
        new_status: MessageStatus,
    ) -> None:
        pass

    @abstractmethod
    def save_extraction_result(
        self,
        message: RawMessage,
        result: ExtractionResult,
        audited_candidates: list[dict[str, Any]],
    ) -> None:
        pass

    @abstractmethod
    def save_error(
        self,
        message: RawMessage,
        error_message: str,
    ) -> None:
        pass

    @abstractmethod
    def rollback(self) -> None:
        pass
