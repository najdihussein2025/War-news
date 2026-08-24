from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.llm.dtos import (
    ExtractionResult,
    RelevanceClassificationResult,
)
from app.llm.services.transient_llm_errors import extraction_retry_cap_message
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
                .options(joinedload(RawMessage.source))
                .where(
                    RawMessage.status == MessageStatus.pending,
                    RawMessage.filter_result.is_(None),
                )
                .order_by(RawMessage.id.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
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
                .with_for_update(skip_locked=True)
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
        message.extraction_retry_count = 0
        self.db.add(message)
        self.db.commit()

    def get_by_id(self, raw_message_id: int) -> RawMessage | None:
        return self.db.get(RawMessage, raw_message_id)

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

    def record_transient_extraction_failure(
        self,
        message: RawMessage,
        exc: BaseException,
        *,
        max_retries: int | None = None,
    ) -> bool:
        """
        Increment retry count for a transient extraction failure.

        Transient failures are parked in ``status=error`` so the same row is
        not immediately reclaimed again within the same sweep. A later sweep can
        re-queue it via ``reset_retryable_extraction_errors``.

        Returns True when the row is permanently capped (status=error).
        """
        limit = (
            max_retries
            if max_retries is not None
            else settings.extraction_max_retries
        )
        message.extraction_retry_count += 1
        message.status = MessageStatus.error
        if message.extraction_retry_count >= limit:
            message.error_message = extraction_retry_cap_message(
                message.extraction_retry_count,
                exc,
            )
            self.db.add(message)
            self.db.commit()
            return True

        message.error_message = f"{type(exc).__name__}: {str(exc).strip() or 'timed out'}"
        self.db.add(message)
        self.db.commit()
        return False

    def reset_retryable_extraction_errors(
        self,
        limit: int = 200,
        *,
        max_retries: int | None = None,
    ) -> tuple[int, int]:
        """Re-queue transient extraction failures, respecting the retry cap."""
        retry_limit = (
            max_retries
            if max_retries is not None
            else settings.extraction_max_retries
        )
        messages = list(
            self.db.scalars(
                select(RawMessage)
                .where(
                    RawMessage.status == MessageStatus.error,
                    RawMessage.extraction_result.is_(None),
                    RawMessage.error_message.is_not(None),
                    or_(
                        RawMessage.error_message.ilike("%ReadTimeout%"),
                        RawMessage.error_message.ilike("%ConnectTimeout%"),
                        RawMessage.error_message.ilike("%TimeoutException%"),
                        RawMessage.error_message.ilike("%timed out%"),
                    ),
                )
                .order_by(RawMessage.id.asc())
                .limit(limit)
            ).all()
        )
        if not messages:
            return 0, 0

        reset_count = 0
        capped_count = 0
        for message in messages:
            if message.extraction_retry_count >= retry_limit:
                if not (message.error_message or "").startswith(
                    "extraction: exceeded max retries"
                ):
                    message.error_message = extraction_retry_cap_message(
                        message.extraction_retry_count,
                        RuntimeError(message.error_message or "timed out"),
                    )
                    self.db.add(message)
                capped_count += 1
                continue

            message.status = MessageStatus.parsed
            message.error_message = None
            self.db.add(message)
            reset_count += 1

        if reset_count or capped_count:
            self.db.commit()
        return reset_count, capped_count

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
        *,
        commit: bool = True,
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
            if commit:
                self.db.commit()
            else:
                self.db.flush()
        except Exception:
            self.db.rollback()
            raise

    def rollback(self) -> None:
        self.db.rollback()
