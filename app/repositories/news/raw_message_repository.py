from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dtos.news import RelevanceClassificationResult
from app.interfaces.news import RawMessageRepositoryInterface
from app.models.news import MessageStatus, RawMessage


class RawMessageRepository(RawMessageRepositoryInterface):
    def get_pending_unfiltered_batch(
        self,
        db: Session,
        limit: int,
    ) -> list[RawMessage]:
        return list(
            db.scalars(
                select(RawMessage)
                .where(
                    RawMessage.status == MessageStatus.pending,
                    RawMessage.filter_result.is_(None),
                )
                .order_by(RawMessage.id.asc())
                .limit(limit)
            ).all()
        )

    def save_filter_result(
        self,
        db: Session,
        message: RawMessage,
        result: RelevanceClassificationResult,
        new_status: str,
    ) -> None:
        message.filter_result = result.model_dump(mode="json")
        message.status = MessageStatus(new_status)
        message.error_message = None
        db.add(message)
        db.commit()

    def save_error(
        self,
        db: Session,
        message: RawMessage,
        error_message: str,
    ) -> None:
        message.status = MessageStatus.error
        message.error_message = error_message
        db.add(message)
        db.commit()
