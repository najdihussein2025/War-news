import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import update

from app.core.config import settings
from app.core.database import SessionLocal
from app.logs.models import IngestionLog
from app.sources.actions import IngestSourceAction
from app.sources.dtos import IngestSourceData
from app.sources.repositories import SourceRepository
from app.sources.services.cnrs_source import CNRSSourceProvider

logger = logging.getLogger("uvicorn.error")

_scheduler: BackgroundScheduler | None = None


def _poll_cnrs() -> None:
    if not settings.cnrs_api_key:
        logger.error("CNRS polling skipped: CNRS_API_KEY is not configured")
        return

    db = SessionLocal()
    run_log: IngestionLog | None = None
    try:
        repository = SourceRepository(db)
        source = repository.get_active_by_external_id("cnrs_webhook")
        if source is None:
            logger.error("CNRS polling skipped: active cnrs_webhook source was not found")
            return

        # A process restart can interrupt a job before its final status update.
        # Close any orphaned run before creating the new current run.
        db.execute(
            update(IngestionLog)
            .where(
                IngestionLog.source_id == source.id,
                IngestionLog.status == "running",
            )
            .values(
                status="interrupted",
                error_message="Ingestion was interrupted by an application restart.",
                finished_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

        run_log = IngestionLog(
            source_id=source.id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        db.add(run_log)
        db.commit()
        db.refresh(run_log)

        action = IngestSourceAction(
            repository,
            provider_factory=lambda configured_source: CNRSSourceProvider(
                config=configured_source.config,
                api_key=settings.cnrs_api_key or "",
            ),
        )
        result = action.execute(
            IngestSourceData(
                source_id=source.id,
                max_batches=10,
                # The API fallback is for missed live webhook deliveries, not for
                # rebuilding the complete CNRS archive. Importing the archive made
                # historical account names appear as newly monitored sources.
                min_message_datetime=datetime.now(timezone.utc) - timedelta(hours=24),
            ),
            write_log=False,
        )
        run_log.status = "completed"
        run_log.messages_fetched = result.fetched
        run_log.messages_parsed = result.inserted
        run_log.messages_failed = result.failed
        run_log.messages_blocked = result.skipped_blocked
        run_log.finished_at = datetime.now(timezone.utc)
        db.add(run_log)
        db.commit()
        logger.info("CNRS polling ingestion result=%s", result.model_dump())
    except Exception as exc:
        db.rollback()
        if run_log is not None:
            run_log.status = "failed"
            run_log.error_message = str(exc)[:2000]
            run_log.finished_at = datetime.now(timezone.utc)
            db.add(run_log)
            db.commit()
        logger.exception("CNRS polling ingestion failed")
    finally:
        db.close()


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _poll_cnrs,
        trigger="interval",
        seconds=settings.ingestion_poll_interval_seconds,
        id="cnrs-polling-ingestion",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        # Do not fire immediately after every backend restart; CNRS may still be
        # enforcing a cooldown from the previous process.
        next_run_time=datetime.now(timezone.utc)
        + timedelta(seconds=settings.ingestion_poll_interval_seconds),
    )
    _scheduler.start()
    logger.info(
        "CNRS polling scheduler started interval_seconds=%s",
        settings.ingestion_poll_interval_seconds,
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
