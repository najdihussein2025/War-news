import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.actions.ingest_source_action import ingest_source
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.news.source import Source

logger = logging.getLogger("uvicorn.error")

CNRS_SOURCE_EXTERNAL_ID = "cnrs_inspected_posts"

_scheduler: BackgroundScheduler | None = None


def _run_cnrs_ingestion() -> None:
    db = SessionLocal()
    try:
        source = db.scalar(
            select(Source).where(
                Source.external_id == CNRS_SOURCE_EXTERNAL_ID,
                Source.is_active.is_(True),
            )
        )
        if source is None:
            logger.warning(
                "CNRS ingestion poll skipped: active source external_id=%r not found",
                CNRS_SOURCE_EXTERNAL_ID,
            )
            return

        min_message_datetime = datetime.now(timezone.utc).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        summary = ingest_source(
            db=db,
            source_id=source.id,
            min_message_datetime=min_message_datetime,
        )
        logger.info(
            "CNRS ingestion poll complete: fetched=%s inserted=%s "
            "skipped_duplicate=%s total_skipped_before_cutoff=%s failed=%s final_cursor=%s",
            summary["fetched"],
            summary["inserted"],
            summary["skipped_duplicate"],
            summary["total_skipped_before_cutoff"],
            summary["failed"],
            summary["final_cursor"],
        )
    except Exception:
        logger.exception("CNRS ingestion poll failed")
    finally:
        db.close()


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _run_cnrs_ingestion,
        "interval",
        seconds=settings.ingestion_poll_interval_seconds,
        id="cnrs_ingestion_poll",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "Started CNRS ingestion scheduler: interval_seconds=%s",
        settings.ingestion_poll_interval_seconds,
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return

    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Stopped CNRS ingestion scheduler")
    _scheduler = None
