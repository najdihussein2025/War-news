import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from app.core.config import settings
from app.core.database import SessionLocal
from app.logs.models import IngestionLog
from app.sources.actions import IngestSourceAction
from app.sources.dtos import IngestSourceData
from app.sources.repositories import SourceRepository
from app.sources.services.cnrs_source import CNRSSourceProvider

logger = logging.getLogger("uvicorn.error")

_cnrs_scheduler: BackgroundScheduler | None = None
_scheduler_thread: threading.Thread | None = None
_scheduler_stop_event: threading.Event | None = None


def _poll_cnrs() -> None:
    if not settings.cnrs_api_key:
        logger.error("CNRS polling skipped: CNRS_API_KEY is not configured")
        return

    db = SessionLocal()
    try:
        repository = SourceRepository(db)
        source = repository.get_active_by_external_id("cnrs_webhook")
        if source is None:
            logger.error("CNRS polling skipped: active cnrs_webhook source was not found")
            return
        started_at = datetime.now(timezone.utc)

        result = IngestSourceAction(
            repository,
            provider_factory=lambda configured_source: CNRSSourceProvider(
                config=configured_source.config,
                api_key=settings.cnrs_api_key or "",
            ),
        ).execute(
            IngestSourceData(
                source_id=source.id,
                page_limit=2000,
                max_batches=10,
                min_message_datetime=datetime.now(timezone.utc) - timedelta(hours=24),
            ),
            write_log=False,
        )
        if result.inserted > 0 or result.failed > 0:
            db.add(
                IngestionLog(
                    source_id=source.id,
                    status="completed",
                    messages_fetched=result.fetched,
                    messages_parsed=result.inserted,
                    messages_failed=result.failed,
                    messages_blocked=result.skipped_blocked,
                    started_at=started_at,
                    finished_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
        logger.info("CNRS polling ingestion result=%s", result.model_dump())
    except Exception as exc:
        db.rollback()
        if 'source' in locals() and source is not None:
            db.add(
                IngestionLog(
                    source_id=source.id,
                    status="failed",
                    error_message=str(exc)[:2000],
                    started_at=started_at if 'started_at' in locals() else None,
                    finished_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
        logger.exception("CNRS polling ingestion failed")
    finally:
        db.close()


def _run_red_alert_loop() -> None:
    poll_seconds = max(10.0, settings.red_alert_poll_seconds)
    logger.info(
        "Red Alert scheduler started delivery_method=%s channel=@%s poll_seconds=%s ocr=%s",
        settings.red_alert_delivery_method,
        settings.red_alert_channel_username,
        poll_seconds,
        settings.red_alert_ocr_enabled,
    )
    while True:
        stop_event = _scheduler_stop_event
        if stop_event is None or stop_event.is_set():
            return

        started_at = time.monotonic()
        try:
            from app.sources.services.red_alert_collector import RedAlertCollector

            with SessionLocal() as db:
                result = RedAlertCollector(
                    db,
                    delivery_method=settings.red_alert_delivery_method,
                    channel_username=settings.red_alert_channel_username,
                    fetch_limit=settings.red_alert_fetch_limit,
                    request_timeout=settings.red_alert_request_timeout_seconds,
                    ocr_enabled=settings.red_alert_ocr_enabled,
                ).collect_once()
            logger.info("Red Alert scheduler cycle result=%s", result)
        except Exception:
            logger.exception("Red Alert scheduler cycle failed")

        if stop_event.wait(max(0.0, poll_seconds - (time.monotonic() - started_at))):
            return


def start_scheduler(*, start_red_alert: bool = True) -> None:
    global _cnrs_scheduler, _scheduler_stop_event, _scheduler_thread

    if _cnrs_scheduler is None:
        _cnrs_scheduler = BackgroundScheduler(timezone="UTC")
        _cnrs_scheduler.add_job(
            _poll_cnrs,
            trigger="interval",
            seconds=settings.ingestion_poll_interval_seconds,
            id="cnrs-polling-ingestion",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=datetime.now(timezone.utc)
            + timedelta(seconds=settings.ingestion_poll_interval_seconds),
        )
        _cnrs_scheduler.start()
        logger.info("CNRS polling scheduler started interval_seconds=%s", settings.ingestion_poll_interval_seconds)

    if not start_red_alert:
        logger.info("Red Alert API scheduler disabled; dedicated collector owns polling")
        return
    if not settings.red_alert_enabled:
        logger.info("Red Alert scheduler disabled; Telegram air-violation polling is off")
        return
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        logger.info("Red Alert scheduler already running")
        return

    _scheduler_stop_event = threading.Event()
    _scheduler_thread = threading.Thread(target=_run_red_alert_loop, name="red-alert-scheduler", daemon=True)
    _scheduler_thread.start()


def stop_scheduler() -> None:
    global _cnrs_scheduler, _scheduler_stop_event, _scheduler_thread

    if _cnrs_scheduler is not None:
        _cnrs_scheduler.shutdown(wait=False)
        _cnrs_scheduler = None
    if _scheduler_stop_event is not None:
        _scheduler_stop_event.set()
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        _scheduler_thread.join(timeout=5)
    _scheduler_stop_event = None
    _scheduler_thread = None
