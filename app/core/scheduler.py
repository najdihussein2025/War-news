import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from app.core.config import settings
from app.core.database import SessionLocal

logger = logging.getLogger("uvicorn.error")

_cnrs_scheduler: BackgroundScheduler | None = None
_scheduler_thread: threading.Thread | None = None
_scheduler_stop_event: threading.Event | None = None


def _uses_cnrs_polling(source) -> bool:
    return False


def _poll_cnrs() -> None:
    # CNRS has one authoritative polling path: the dedicated
    # cnrs-poll-worker container, which owns the numeric resume cursor and logs
    # "CNRS poll pass complete: {...}" every pass. The backend scheduler must
    # not also poll this source or both processes can race on cursor updates.
    # The HTTP webhook handler remains available for any future CNRS push.
    logger.info("CNRS backend scheduler no-op: cnrs-poll-worker owns polling")


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
