from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dtos.news import ExtractionResult, RelevanceClassificationResult
from app.interfaces.news import RawMessageRepositoryInterface
from app.models.news import MessageStatus, RawMessage


class RawMessageRepository(RawMessageRepositoryInterface):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_pending_unfiltered_batch(
        self,
        limit: int,
    ) -> list[RawMessage]:
        return list(
            self.db.scalars(
                select(RawMessage)
                .where(
                    RawMessage.status == MessageStatus.pending,
                    RawMessage.filter_result.is_(None),
                )
                .order_by(RawMessage.id.asc())
                .limit(limit)
            ).all()
        )

    def get_pending_extraction_batch(
        self,
        limit: int,
    ) -> list[RawMessage]:
        return list(
            self.db.scalars(
                select(RawMessage)
                .where(
                    RawMessage.status == MessageStatus.parsed,
                    RawMessage.extraction_result.is_(None),
                )
                .order_by(RawMessage.id.asc())
                .limit(limit)
            ).all()
        )

    def save_filter_result(
        self,
        message: RawMessage,
        result: RelevanceClassificationResult,
        new_status: MessageStatus,
    ) -> None:
        message.filter_result = result.model_dump(mode="json")
        message.status = new_status
        message.error_message = None
        self.db.add(message)
        self.db.commit()

    def save_extraction_result(
        self,
        message: RawMessage,
        result: ExtractionResult,
        audited_candidates: list[dict[str, Any]],
    ) -> None:
        message.extraction_result = {
            **result.model_dump(mode="json"),
            "candidates": audited_candidates,
        }
        message.error_message = None
        self.db.add(message)
        self.db.commit()

    def save_error(
        self,
        message: RawMessage,
        error_message: str,
    ) -> None:
        message.status = MessageStatus.error
        message.error_message = error_message
        self.db.add(message)
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()
