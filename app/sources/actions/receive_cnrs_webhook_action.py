from datetime import datetime, timezone
import logging

from sqlalchemy.exc import IntegrityError

from app.sources.dtos import (
    CnrsWebhookPayload,
    CnrsWebhookPostDTO,
)
from app.sources.interfaces import SourceRepositoryInterface
from app.news.models import (
    MessageStatus,
    RawMessage,
)
from app.sources.services.cnrs_source import CNRS_CLASSIFICATION_FIELDS

logger = logging.getLogger(__name__)


def _platform_counts(breakdown: dict[str, dict[str, int]], platform: str | None) -> dict[str, int]:
    key = (platform or "unknown").lower()
    return breakdown.setdefault(key, {"fetched": 0, "parsed": 0, "flagged": 0, "failed": 0, "blocked": 0})


def _derive_platform_from_external_id(external_message_id: str | None) -> str | None:
    if not external_message_id or ":" not in external_message_id:
        return None
    platform, _message_id = external_message_id.split(":", 1)
    return platform or None


class ReceiveCnrsWebhookAction:
    def __init__(self, sources: SourceRepositoryInterface) -> None:
        self.sources = sources

    def execute(self, payload: CnrsWebhookPayload, source_id: int) -> dict[str, int]:
        posts = self._normalize_payload(payload)
        source = self.sources.get_by_id(source_id)
        started_at = datetime.now(timezone.utc)
        saved = 0
        duplicates = 0
        blocked = 0
        failed = 0
        flagged = 0
        source_platforms: set[str] = set()
        platform_breakdown: dict[str, dict[str, int]] = {}

        try:
            for post in posts:
                counts: dict[str, int] | None = None
                try:
                    raw_payload = post.model_dump(mode="json")
                    classification = {
                        key: raw_payload[key]
                        for key in CNRS_CLASSIFICATION_FIELDS
                        if key in raw_payload
                    }
                    if classification.get("include") is False:
                        flagged += 1
                    source_platform = raw_payload.get(
                        "source_platform"
                    ) or _derive_platform_from_external_id(post.external_message_id)
                    if source_platform:
                        source_platforms.add(source_platform.lower())
                    counts = _platform_counts(platform_breakdown, source_platform)
                    counts["fetched"] += 1
                    if classification.get("include") is False:
                        counts["flagged"] += 1
                    source_name = raw_payload.get("source_name") or (
                        source.name if source is not None else None
                    )
                    source_platform_id = self.sources.get_or_create_source_platform_id(
                        source_platform,
                        source_name,
                    )
                    origin_account = raw_payload.get("origin_account") or source_name
                    if self.sources.is_content_source_blocked(
                        source_platform,
                        origin_account,
                    ):
                        blocked += 1
                        counts["blocked"] += 1
                        continue

                    self.sources.add_raw_message(
                        RawMessage(
                            source_id=source_id,
                            external_message_id=post.external_message_id,
                            source_platform=source_platform,
                            source_name=source_name,
                            source_platform_id=source_platform_id,
                            origin_platform=source_platform,
                            origin_account=origin_account,
                            cnrs_classification=classification or None,
                            raw_text=post.raw_text,
                            raw_payload=raw_payload,
                            message_datetime=post.message_datetime,
                            status=MessageStatus.pending,
                        )
                    )
                    saved += 1
                    counts["parsed"] += 1
                except IntegrityError as exc:
                    if not self.sources.is_duplicate_raw_message_error(exc):
                        failed += 1
                        if counts is not None:
                            counts["failed"] += 1
                        self.sources.rollback()
                        raise
                    duplicates += 1
                except Exception:
                    failed += 1
                    if counts is not None:
                        counts["failed"] += 1
                    logger.exception(
                        "Failed to ingest CNRS webhook post external_message_id=%s",
                        post.external_message_id,
                    )

            self.sources.commit()
            return {
                "received": len(posts),
                "saved": saved,
                "duplicates": duplicates,
                "blocked": blocked,
            }
        finally:
            if saved > 0 or failed > 0:
                self.sources.write_ingestion_log(
                    source_id=source_id,
                    messages_fetched=len(posts),
                    messages_parsed=saved,
                    messages_failed=failed,
                    messages_flagged=flagged,
                    started_at=started_at,
                    messages_blocked=blocked,
                    source_platforms=sorted(source_platforms),
                    platform_breakdown=platform_breakdown,
                )

    @staticmethod
    def _normalize_payload(payload: CnrsWebhookPayload) -> list[CnrsWebhookPostDTO]:
        if isinstance(payload, list):
            return payload
        return [payload]
