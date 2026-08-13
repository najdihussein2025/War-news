import logging
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.news.ingestion_log import IngestionLog
from app.models.news.raw_message import MessageStatus, RawMessage
from app.models.news.source import Source
from app.sources.cnrs_source import CNRSSourceProvider

logger = logging.getLogger(__name__)


class SourceIngestionError(Exception):
    pass


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


def _is_duplicate_raw_message_error(exc: IntegrityError) -> bool:
    constraint_name = getattr(
        getattr(exc.orig, "diag", None),
        "constraint_name",
        None,
    )
    return (
        constraint_name == "uq_raw_messages_source_external_message"
        or "uq_raw_messages_source_external_message" in str(exc.orig)
    )


def ingest_source(db: Session, source_id: int, page_limit: int = 500) -> dict:
    source = db.get(Source, source_id)
    if source is None:
        raise SourceIngestionError(f"Source id={source_id} was not found.")

    if not source.is_active:
        raise SourceIngestionError(f"Source id={source_id} is inactive.")

    if not source.auth_secret_ref:
        raise SourceIngestionError(
            f"Source id={source_id} does not define auth_secret_ref."
        )

    api_key = os.environ.get(source.auth_secret_ref)
    if not api_key:
        raise SourceIngestionError(
            f"Environment variable {source.auth_secret_ref!r} is not set."
        )

    provider = CNRSSourceProvider(config=source.config, api_key=api_key)
    started_at = datetime.now(timezone.utc)
    total_fetched = 0
    total_inserted = 0
    total_skipped_duplicate = 0
    total_failed = 0
    source_db_id = source.id

    try:
        while True:
            items, next_cursor, has_more = provider.fetch_batch(
                cursor=source.last_cursor,
                limit=page_limit,
            )
            total_fetched += len(items)

            if not items:
                source.last_cursor = next_cursor
                db.commit()
                break

            for item in items:
                try:
                    message_datetime = _parse_message_datetime(
                        item.get("message_datetime")
                    )
                    raw_message = RawMessage(
                        source_id=source.id,
                        external_message_id=item.get("external_message_id"),
                        source_platform=item.get("source_platform"),
                        source_name=item.get("source_name"),
                        origin_platform=item.get("origin_platform"),
                        origin_account=item.get("origin_account"),
                        cnrs_classification=item.get("cnrs_classification"),
                        raw_text=item.get("raw_text"),
                        raw_payload=item.get("raw_payload") or item,
                        message_datetime=message_datetime,
                        status=MessageStatus.pending,
                    )
                    with db.begin_nested():
                        db.add(raw_message)
                        db.flush()
                    total_inserted += 1
                except IntegrityError as exc:
                    if _is_duplicate_raw_message_error(exc):
                        total_skipped_duplicate += 1
                    else:
                        total_failed += 1
                        logger.exception("Failed to insert raw message.")
                except Exception:
                    total_failed += 1
                    logger.exception("Failed to process raw message.")

            source.last_cursor = next_cursor
            db.add(source)
            db.commit()

            if not has_more:
                break
    except Exception:
        logger.exception(
            "CNRS ingestion failed after fetched=%s inserted=%s skipped_duplicate=%s failed=%s",
            total_fetched,
            total_inserted,
            total_skipped_duplicate,
            total_failed,
        )
        _write_ingestion_log(
            db=db,
            source_id=source_db_id,
            messages_fetched=total_fetched,
            messages_parsed=total_inserted,
            messages_failed=total_failed,
            started_at=started_at,
        )
        raise

    _write_ingestion_log(
        db=db,
        source_id=source_db_id,
        messages_fetched=total_fetched,
        messages_parsed=total_inserted,
        messages_failed=total_failed,
        started_at=started_at,
    )

    return {
        "fetched": total_fetched,
        "inserted": total_inserted,
        "skipped_duplicate": total_skipped_duplicate,
        "failed": total_failed,
        "final_cursor": source.last_cursor,
    }


def _write_ingestion_log(
    db: Session,
    source_id: int,
    messages_fetched: int,
    messages_parsed: int,
    messages_failed: int,
    started_at: datetime,
) -> None:
    db.rollback()
    ingestion_log = IngestionLog(
        source_id=source_id,
        messages_fetched=messages_fetched,
        messages_parsed=messages_parsed,
        messages_flagged=0,
        messages_failed=messages_failed,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
    )
    db.add(ingestion_log)
    db.commit()
