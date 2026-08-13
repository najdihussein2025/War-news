from sqlalchemy.exc import IntegrityError

from app.dtos.news import CnrsWebhookPayload, CnrsWebhookPostDTO
from app.interfaces.repositories import SourceRepositoryInterface
from app.models.news import MessageStatus, RawMessage


class ReceiveCnrsWebhookAction:
    def __init__(self, sources: SourceRepositoryInterface) -> None:
        self.sources = sources

    def execute(self, payload: CnrsWebhookPayload, source_id: int) -> dict[str, int]:
        posts = self._normalize_payload(payload)
        saved = 0
        duplicates = 0

        for post in posts:
            try:
                self.sources.add_raw_message(
                    RawMessage(
                        source_id=source_id,
                        external_message_id=post.external_message_id,
                        raw_text=post.raw_text,
                        raw_payload=post.model_dump(mode="json"),
                        message_datetime=post.message_datetime,
                        status=MessageStatus.pending,
                    )
                )
                saved += 1
            except IntegrityError as exc:
                if not self.sources.is_duplicate_raw_message_error(exc):
                    self.sources.rollback()
                    raise
                duplicates += 1

        self.sources.commit()
        return {
            "received": len(posts),
            "saved": saved,
            "duplicates": duplicates,
        }

    @staticmethod
    def _normalize_payload(payload: CnrsWebhookPayload) -> list[CnrsWebhookPostDTO]:
        if isinstance(payload, list):
            return payload
        return [payload]
