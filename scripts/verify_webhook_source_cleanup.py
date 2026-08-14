from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.llm.actions import (
    ExtractIncidentsAction,
    FilterRelevanceAction,
)
from app.core.database import SessionLocal
from app.llm.dtos import (
    ClassificationResultDTO,
    ClassificationVerdict,
    ExtractPendingMessagesData,
    ExtractionResult,
    FilterPendingMessagesData,
)
from app.news.interfaces import RawMessageRepositoryInterface
from app.llm.interfaces import (
    ExtractionClassifierInterface,
    KeywordPrefilterInterface,
)
from app.news.models import (
    MessageStatus,
    RawMessage,
)
from app.sources.models import Source


class AlwaysCandidateKeywordPrefilter(KeywordPrefilterInterface):
    def has_candidate_keywords(self, text: str) -> bool:
        return True


class StubRelevanceClassifier:
    async def classify_batch(
        self,
        messages: list[RawMessage],
    ) -> list[ClassificationResultDTO]:
        await asyncio.sleep(0)
        return [
            ClassificationResultDTO(
                raw_message_id=message.id,
                verdict=ClassificationVerdict.relevant,
                confidence=0.99,
                reasoning="cleanup sanity check",
                backend="stub",
            )
            for message in messages
        ]


class StubExtractionClassifier(ExtractionClassifierInterface):
    def extract(
        self,
        post_text: str,
        raw_message_id: int | None = None,
    ) -> ExtractionResult:
        return ExtractionResult(
            is_relevant=True,
            village=None,
            action_description="cleanup sanity check",
            model="stub",
            extracted_at=datetime.now(timezone.utc),
        )


class InMemoryRawMessageRepository(RawMessageRepositoryInterface):
    def __init__(
        self,
        pending_messages: list[RawMessage],
        parsed_messages: list[RawMessage],
    ) -> None:
        self.pending_messages = pending_messages
        self.parsed_messages = parsed_messages

    def get_pending_unfiltered_batch(self, limit: int) -> list[RawMessage]:
        return self.pending_messages[:limit]

    def get_pending_extraction_batch(self, limit: int) -> list[RawMessage]:
        return self.parsed_messages[:limit]

    def save_filter_result(
        self,
        message: RawMessage,
        result,
        new_status: MessageStatus,
        needs_review: bool = False,
    ) -> None:
        message.filter_result = result.model_dump(mode="json")
        message.status = new_status

    def save_extraction_result(
        self,
        message: RawMessage,
        result: ExtractionResult,
        audited_candidates: list[dict[str, object]],
    ) -> None:
        message.extraction_result = result.model_dump(mode="json")

    def get_parsed_by_id(self, raw_message_id: int) -> RawMessage | None:
        return next(
            (message for message in self.parsed_messages if message.id == raw_message_id),
            None,
        )

    def save_match_result(self, message: RawMessage, result) -> None:
        message.match_result = result.model_dump(mode="json")

    def save_error(self, message: RawMessage, error_message: str) -> None:
        message.status = MessageStatus.error
        message.error_message = error_message

    def rollback(self) -> None:
        return


def main() -> None:
    with SessionLocal() as db:
        sources = db.execute(select(Source.id, Source.name).order_by(Source.id.asc())).all()
        dangling_raw_messages = db.scalar(
            select(func.count(RawMessage.id))
            .select_from(RawMessage)
            .outerjoin(Source, Source.id == RawMessage.source_id)
            .where(Source.id.is_(None))
        )
        webhook_source_id = db.scalar(
            select(Source.id).where(Source.name == "CNRS Webhook")
        )

        if webhook_source_id is None:
            raise RuntimeError("CNRS Webhook source was not found.")

        pending_messages = list(
            db.scalars(
                select(RawMessage)
                .where(
                    RawMessage.source_id == webhook_source_id,
                    RawMessage.status == MessageStatus.pending,
                    RawMessage.filter_result.is_(None),
                )
                .order_by(RawMessage.id.asc())
                .limit(1)
            )
        )
        parsed_messages = list(
            db.scalars(
                select(RawMessage)
                .where(
                    RawMessage.source_id == webhook_source_id,
                    RawMessage.status == MessageStatus.parsed,
                    RawMessage.extraction_result.is_(None),
                )
                .order_by(RawMessage.id.asc())
                .limit(1)
            )
        )

    repository = InMemoryRawMessageRepository(
        pending_messages=pending_messages,
        parsed_messages=parsed_messages,
    )
    relevance_summary = FilterRelevanceAction(
        raw_messages=repository,
        classifier=StubRelevanceClassifier(),
        keyword_prefilter=AlwaysCandidateKeywordPrefilter(),
        relevance_batch_size=1,
    ).execute(FilterPendingMessagesData(batch_size=1))
    extraction_summary = ExtractIncidentsAction(
        raw_messages=repository,
        classifier=StubExtractionClassifier(),
    ).execute(ExtractPendingMessagesData(batch_size=1))

    print(
        {
            "sources": [dict(row._mapping) for row in sources],
            "only_cnrs_webhook": [row.name for row in sources] == ["CNRS Webhook"],
            "dangling_raw_messages": dangling_raw_messages,
            "webhook_pending_messages_sampled": len(pending_messages),
            "webhook_parsed_messages_sampled": len(parsed_messages),
            "relevance_summary": relevance_summary.model_dump(),
            "extraction_summary": extraction_summary.model_dump(),
        }
    )


if __name__ == "__main__":
    main()
