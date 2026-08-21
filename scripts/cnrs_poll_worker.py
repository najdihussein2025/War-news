import argparse
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import BigInteger, cast, func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import SessionLocal
from app.news.models import MessageStatus, RawMessage
from app.sources.actions.ingest_source_action import _derive_platform_from_external_id
from app.sources.actions.receive_cnrs_webhook_action import _platform_counts
from app.sources.repositories.source_repository import SourceRepository
from app.sources.services.cnrs_source import CNRSSourceProvider

logger = logging.getLogger(__name__)

SOURCE_ID = 3
PAGE_LIMIT = 500


def _resolve_cnrs_api_key(auth_secret_ref: str | None) -> str:
    if auth_secret_ref:
        secret = os.environ.get(auth_secret_ref)
        if secret:
            return secret

    if settings.cnrs_api_key:
        return settings.cnrs_api_key

    raise RuntimeError(
        "CNRS API key is not configured. Set the source auth_secret_ref env var "
        "or CNRS_API_KEY."
    )


def _parse_message_datetime(value: object) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    if not isinstance(value, str) or not value.strip():
        return None

    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    return datetime.fromisoformat(normalized)


def _last_ingested_cursor(repo: SourceRepository, source_id: int) -> str | None:
    # CNRS polling stores the provider's numeric post id as a string in
    # raw_messages.external_message_id, so resume order must cast numerically.
    # Historical CNRS webhook rows used prefixed ids, so this only resumes from
    # poll-worker-inserted rows once numeric ids exist.
    statement = select(
        func.max(cast(RawMessage.external_message_id, BigInteger))
    ).where(
        RawMessage.source_id == source_id,
        RawMessage.external_message_id.is_not(None),
        RawMessage.external_message_id.op("~")(r"^[0-9]+$"),
    )
    value = repo.db.scalar(statement)
    return str(value) if value is not None else None


def _parse_after_id_arg(value: str) -> str:
    normalized = value.strip()
    if not normalized or not normalized.isdigit():
        raise argparse.ArgumentTypeError("--after-id must be a numeric CNRS post id.")
    return normalized


def _resolve_resume_cursor(
    repo: SourceRepository,
    source_id: int,
    override_after_id: str | None,
) -> str:
    if override_after_id is not None:
        logger.info(
            "Using explicit CNRS resume cursor override for this run: after_id=%s",
            override_after_id,
        )
        return override_after_id

    current_cursor = _last_ingested_cursor(repo, source_id)
    if current_cursor is not None:
        return current_cursor

    logger.warning(
        "No numeric CNRS resume cursor found for source_id=%s; refusing to "
        "default to after_id=0. Pass --after-id <numeric_cnrs_post_id> for "
        "the first poll-worker run.",
        source_id,
    )
    raise RuntimeError(
        "CNRS poll worker requires --after-id <numeric_cnrs_post_id> on the "
        "first run when no numeric resume cursor exists."
    )


def _effective_next_cursor(
    current_cursor: str | None,
    next_cursor: str | None,
    items: list[dict],
) -> str | None:
    if next_cursor is not None:
        return str(next_cursor)

    if items:
        last_external_message_id = items[-1].get("external_message_id")
        if isinstance(last_external_message_id, str) and last_external_message_id:
            return last_external_message_id

    return current_cursor


def run_poll_pass(
    source_id: int = SOURCE_ID,
    page_limit: int = PAGE_LIMIT,
    after_id: str | None = None,
) -> dict[str, int | str | None]:
    db = SessionLocal()
    try:
        repo = SourceRepository(db)
        source = repo.get_by_id(source_id)
        if source is None:
            raise RuntimeError(f"Source id={source_id} was not found.")
        if not source.is_active:
            raise RuntimeError(f"Source id={source_id} is inactive.")

        provider = CNRSSourceProvider(
            config=source.config,
            api_key=_resolve_cnrs_api_key(source.auth_secret_ref),
        )
        started_at = datetime.now(timezone.utc)
        current_cursor = _resolve_resume_cursor(repo, source_id, after_id)
        fetched = 0
        inserted = 0
        duplicates = 0
        blocked = 0
        failed = 0
        flagged = 0
        source_platforms: set[str] = set()
        platform_breakdown: dict[str, dict[str, int]] = {}

        try:
            while True:
                items, next_cursor, has_more = provider.fetch_batch(
                    cursor=current_cursor,
                    limit=page_limit,
                )
                fetched += len(items)

                for item in items:
                    counts: dict[str, int] | None = None
                    try:
                        external_message_id = item.get("external_message_id")
                        classification = item.get("cnrs_classification") or {}
                        if classification.get("include") is False:
                            flagged += 1

                        source_platform = item.get(
                            "source_platform"
                        ) or _derive_platform_from_external_id(external_message_id)
                        if source_platform:
                            source_platforms.add(source_platform.lower())
                        counts = _platform_counts(platform_breakdown, source_platform)
                        counts["fetched"] += 1
                        if classification.get("include") is False:
                            counts["flagged"] += 1

                        source_name = item.get("source_name") or source.name
                        origin_account = item.get("origin_account") or source_name
                        if repo.is_content_source_blocked(
                            source_platform,
                            origin_account,
                        ):
                            blocked += 1
                            counts["blocked"] += 1
                            continue

                        repo.add_raw_message(
                            RawMessage(
                                source_id=source_id,
                                external_message_id=external_message_id,
                                source_platform=source_platform,
                                source_name=source_name,
                                origin_platform=item.get("origin_platform")
                                or source_platform,
                                origin_account=origin_account,
                                cnrs_classification=classification or None,
                                raw_text=item.get("raw_text"),
                                raw_payload=item.get("raw_payload") or item,
                                message_datetime=_parse_message_datetime(
                                    item.get("message_datetime")
                                ),
                                status=MessageStatus.pending,
                            )
                        )
                        inserted += 1
                        counts["parsed"] += 1
                    except IntegrityError as exc:
                        if not repo.is_duplicate_raw_message_error(exc):
                            failed += 1
                            if counts is not None:
                                counts["failed"] += 1
                            repo.rollback()
                            raise
                        duplicates += 1
                    except Exception:
                        failed += 1
                        if counts is not None:
                            counts["failed"] += 1
                        logger.exception(
                            "Failed to ingest CNRS polled post external_message_id=%s",
                            item.get("external_message_id"),
                        )

                current_cursor = _effective_next_cursor(
                    current_cursor=current_cursor,
                    next_cursor=next_cursor,
                    items=items,
                )
                repo.update_last_cursor(source, current_cursor)

                if not has_more or not items:
                    break
        finally:
            repo.write_ingestion_log(
                source_id=source_id,
                messages_fetched=fetched,
                messages_parsed=inserted,
                messages_failed=failed,
                started_at=started_at,
                messages_blocked=blocked,
                messages_flagged=flagged,
                source_platforms=sorted(source_platforms),
                platform_breakdown=platform_breakdown,
            )

        summary = {
            "source_id": source_id,
            "resume_cursor": current_cursor,
            "fetched": fetched,
            "inserted": inserted,
            "duplicates": duplicates,
            "blocked": blocked,
            "failed": failed,
        }
        logger.info("CNRS poll pass complete: %s", summary)
        return summary
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Poll CNRS for new posts and ingest them into raw_messages."
    )
    parser.add_argument(
        "--after-id",
        type=_parse_after_id_arg,
        help="Override the resume cursor for this run only with a numeric CNRS post id.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    summary = run_poll_pass(after_id=args.after_id)
    logger.info(
        "CNRS poll worker exiting fetched=%s inserted=%s duplicates=%s blocked=%s failed=%s cursor=%s",
        summary["fetched"],
        summary["inserted"],
        summary["duplicates"],
        summary["blocked"],
        summary["failed"],
        summary["resume_cursor"],
    )


if __name__ == "__main__":
    main()
