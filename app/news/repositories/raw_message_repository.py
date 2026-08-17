from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.dtos import (
    ExtractionResult,
    RelevanceClassificationResult,
)
from app.news.dtos import MatchResultDTO
from app.news.interfaces import RawMessageRepositoryInterface
from app.news.models import (
    MessageStatus,
    RawMessage,
)


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
                    RawMessage.duplicate_of_id.is_(None),
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

    def save_content_embedding(
        self,
        raw_message_id: int,
        embedding: list[float],
    ) -> None:
        message = self.db.get(RawMessage, raw_message_id)
        if message is None:
            raise ValueError(f"RawMessage id={raw_message_id} not found")
        message.content_embedding = embedding
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

    def mark_as_duplicate(
        self,
        raw_message_id: int,
        representative_id: int,
    ) -> None:
        message = self.db.get(RawMessage, raw_message_id)
        if message is None:
            raise ValueError(f"RawMessage id={raw_message_id} not found")
        message.duplicate_of_id = representative_id
        message.status = MessageStatus.duplicate
        self.db.add(message)
        self.db.commit()

    def mark_cluster_duplicates(
        self,
        representative_id: int,
        member_ids: list[int],
    ) -> None:
        if not member_ids:
            return

        unique_member_ids = set(member_ids)
        try:
            messages = list(
                self.db.scalars(
                    select(RawMessage).where(RawMessage.id.in_(unique_member_ids))
                ).all()
            )
            found_ids = {message.id for message in messages}
            missing_ids = unique_member_ids - found_ids
            if missing_ids:
                missing = ", ".join(str(message_id) for message_id in sorted(missing_ids))
                raise ValueError(f"RawMessage ids not found: {missing}")

            for message in messages:
                message.duplicate_of_id = representative_id
                message.status = MessageStatus.duplicate
                self.db.add(message)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def rollback(self) -> None:
        self.db.rollback()
