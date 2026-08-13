from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dtos.news import (
    ExtractionResult,
    MatchResultDTO,
    RelevanceClassificationResult,
)
from app.interfaces.repositories import RawMessageRepositoryInterface
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
        needs_review: bool = False,
    ) -> None:
        filter_result = result.model_dump(mode="json")
        filter_result["needs_review"] = needs_review
        message.filter_result = filter_result
        message.status = new_status
        message.low_confidence_relevance = needs_review
        message.error_message = None
        self.db.add(message)
        self.db.commit()

    def save_extraction_result(
        self,
        message: RawMessage,
        result: ExtractionResult,
        audited_candidates: list[dict[str, Any]],
    ) -> None:
        message.extraction_result = result.model_dump(mode="json")
        if audited_candidates:
            message.extraction_result["candidates"] = audited_candidates
        message.error_message = None
        self.db.add(message)
        self.db.commit()

    def get_parsed_by_id(self, raw_message_id: int) -> RawMessage | None:
        return self.db.scalar(
            select(RawMessage).where(
                RawMessage.id == raw_message_id,
                RawMessage.status == MessageStatus.parsed,
            )
        )

    def save_match_result(
        self,
        message: RawMessage,
        result: MatchResultDTO,
    ) -> None:
        message.match_result = result.model_dump(mode="json")
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
