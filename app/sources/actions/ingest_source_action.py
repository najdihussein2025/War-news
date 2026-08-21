import logging
import os
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.sources.dtos import (
    IngestSourceData,
    IngestionSummary,
)
from app.sources.interfaces import SourceRepositoryInterface
from app.sources.interfaces.source_provider import SourceProvider
from app.news.models import (
    MessageStatus,
    RawMessage,
)
from app.sources.models import Source
from app.sources.services.cnrs_source import CNRSSourceProvider

logger = logging.getLogger(__name__)


def _derive_platform_from_external_id(external_message_id: str | None) -> str | None:
    if not external_message_id or ":" not in external_message_id:
        return None
    platform, _message_id = external_message_id.split(":", 1)
    return platform or None


class SourceIngestionError(Exception):
    pass


class IngestSourceAction:
    def __init__(
        self,
        sources: SourceRepositoryInterface,
        provider_factory: Callable[[Source], SourceProvider] | None = None,
    ) -> None:
        self.sources = sources
        self.provider_factory = provider_factory or self._build_cnrs_provider

    def execute(
        self,
        data: IngestSourceData,
        *,
        write_log: bool = True,
    ) -> IngestionSummary:
        source = self.sources.get_by_id(data.source_id)
        if source is None:
            raise SourceIngestionError(f"Source id={data.source_id} was not found.")

        if not source.is_active:
            raise SourceIngestionError(f"Source id={data.source_id} is inactive.")

        provider = self.provider_factory(source)
        started_at = datetime.now(timezone.utc)
        total_fetched = 0
        total_inserted = 0
        total_skipped_duplicate = 0
        total_skipped_before_cutoff = 0
        total_skipped_blocked = 0
        total_failed = 0
        batches_fetched = 0
        source_platforms: set[str] = set()
        source_db_id = source.id

        try:
            while True:
                items, next_cursor, has_more = provider.fetch_batch(
                    cursor=source.last_cursor,
                    limit=data.page_limit,
                )
                batches_fetched += 1
                total_fetched += len(items)

                if not items:
                    self.sources.update_last_cursor(source, next_cursor)
                    break

                for item in items:
                    try:
                        message_datetime = self._parse_message_datetime(
                            item.get("message_datetime")
                        )
                        if self._is_before_cutoff(
                            message_datetime,
                            data.min_message_datetime,
                        ):
                            total_skipped_before_cutoff += 1
                            continue

                        external_message_id = item.get("external_message_id")
                        source_platform = item.get(
                            "source_platform"
                        ) or _derive_platform_from_external_id(external_message_id)
                        if source_platform:
                            source_platforms.add(source_platform.lower())
                        source_name = item.get("source_name") or source.name
                        source_platform_id = self.sources.get_or_create_source_platform_id(
                            source_platform,
                            source_name,
                        )
                        origin_account = item.get("origin_account") or source_name
                        if self.sources.is_content_source_blocked(
                            source_platform,
                            origin_account,
                        ):
                            total_skipped_blocked += 1
                            continue

                        self.sources.add_raw_message(
                            RawMessage(
                                source_id=source.id,
                                external_message_id=external_message_id,
                                source_platform=source_platform,
                                source_name=source_name,
                                source_platform_id=source_platform_id,
                                origin_platform=item.get("origin_platform")
                                or source_platform,
                                origin_account=origin_account,
                                cnrs_classification=item.get("cnrs_classification"),
                                raw_text=item.get("raw_text"),
                                raw_payload=item.get("raw_payload") or item,
                                message_datetime=message_datetime,
                                status=MessageStatus.pending,
                            )
                        )
                        total_inserted += 1
                    except IntegrityError as exc:
                        if self.sources.is_duplicate_raw_message_error(exc):
                            total_skipped_duplicate += 1
                        else:
                            total_failed += 1
                            logger.exception("Failed to insert raw message.")
                    except Exception:
                        total_failed += 1
                        logger.exception("Failed to process raw message.")

                self.sources.update_last_cursor(source, next_cursor)

                if not has_more or (
                    data.max_batches is not None
                    and batches_fetched >= data.max_batches
                ):
                    break
        except Exception:
            logger.exception(
                "CNRS ingestion failed after fetched=%s inserted=%s "
                "skipped_duplicate=%s skipped_before_cutoff=%s "
                "skipped_blocked=%s failed=%s",
                total_fetched,
                total_inserted,
                total_skipped_duplicate,
                total_skipped_before_cutoff,
                total_skipped_blocked,
                total_failed,
            )
            if write_log:
                self.sources.write_ingestion_log(
                    source_id=source_db_id,
                    messages_fetched=total_fetched,
                    messages_parsed=total_inserted,
                    messages_failed=total_failed,
                    started_at=started_at,
                    messages_blocked=total_skipped_blocked,
                    source_platforms=sorted(source_platforms),
                )
            raise

        if write_log:
            self.sources.write_ingestion_log(
                source_id=source_db_id,
                messages_fetched=total_fetched,
                messages_parsed=total_inserted,
                messages_failed=total_failed,
                started_at=started_at,
                messages_blocked=total_skipped_blocked,
                source_platforms=sorted(source_platforms),
            )

        return IngestionSummary(
            fetched=total_fetched,
            inserted=total_inserted,
            skipped_duplicate=total_skipped_duplicate,
            skipped_before_cutoff=total_skipped_before_cutoff,
            skipped_blocked=total_skipped_blocked,
            failed=total_failed,
            final_cursor=source.last_cursor,
        )

    @staticmethod
    def _build_cnrs_provider(source: Source) -> SourceProvider:
        # The CNRS source receives webhooks and also supports API polling. Its
        # auth_secret_ref therefore points at the inbound webhook secret, which
        # must never be sent to the CNRS API as a bearer token.
        if source.external_id == "cnrs_webhook":
            if not settings.cnrs_api_key:
                raise SourceIngestionError("CNRS_API_KEY is not configured.")
            return CNRSSourceProvider(
                config=source.config,
                api_key=settings.cnrs_api_key,
            )

        if not source.auth_secret_ref:
            raise SourceIngestionError(
                f"Source id={source.id} does not define auth_secret_ref."
            )

        api_key = os.environ.get(source.auth_secret_ref)
        if not api_key:
            raise SourceIngestionError(
                f"Environment variable {source.auth_secret_ref!r} is not set."
            )

        return CNRSSourceProvider(config=source.config, api_key=api_key)

    @staticmethod
    def _parse_message_datetime(value: Any) -> datetime | None:
        if value is None:
            return None

        if isinstance(value, datetime):
            return value

        if not isinstance(value, str) or not value.strip():
            return None

        try:
            normalized = value.strip()
            if normalized.endswith("Z"):
                normalized = f"{normalized[:-1]}+00:00"
            return datetime.fromisoformat(normalized)
        except ValueError:
            logger.warning("Could not parse message_datetime value: %r", value)
            return None

    @staticmethod
    def _is_before_cutoff(
        message_datetime: datetime | None,
        min_message_datetime: datetime | None,
    ) -> bool:
        if min_message_datetime is None:
            return False

        if message_datetime is None:
            return True

        normalized_message_datetime = message_datetime
        normalized_min_datetime = min_message_datetime
        if normalized_message_datetime.tzinfo is None:
            normalized_message_datetime = normalized_message_datetime.replace(
                tzinfo=timezone.utc
            )
        if normalized_min_datetime.tzinfo is None:
            normalized_min_datetime = normalized_min_datetime.replace(
                tzinfo=timezone.utc
            )

        return normalized_message_datetime < normalized_min_datetime
