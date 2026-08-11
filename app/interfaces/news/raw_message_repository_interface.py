from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from app.dtos.news import RelevanceClassificationResult
from app.models.news import RawMessage


class RawMessageRepositoryInterface(ABC):
    @abstractmethod
    def get_pending_unfiltered_batch(
        self,
        db: Session,
        limit: int,
    ) -> list[RawMessage]:
        pass

    @abstractmethod
    def save_filter_result(
        self,
        db: Session,
        message: RawMessage,
        result: RelevanceClassificationResult,
        new_status: str,
    ) -> None:
        pass

    @abstractmethod
    def save_error(
        self,
        db: Session,
        message: RawMessage,
        error_message: str,
    ) -> None:
        pass
