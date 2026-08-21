import logging
import threading
import time

from app.core.config import settings
from app.core.database import SessionLocal

logger = logging.getLogger("uvicorn.error")

_scheduler_thread: threading.Thread | None = None
_scheduler_stop_event: threading.Event | None = None


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

        elapsed = time.monotonic() - started_at
        wait_seconds = max(0.0, poll_seconds - elapsed)
        if stop_event.wait(wait_seconds):
            return


def start_scheduler() -> None:
    global _scheduler_stop_event, _scheduler_thread

    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        logger.info("Red Alert scheduler already running")
        return

    if not settings.red_alert_enabled:
        logger.info("Red Alert scheduler disabled; Telegram air-violation polling is off")
        return

    _scheduler_stop_event = threading.Event()
    _scheduler_thread = threading.Thread(
        target=_run_red_alert_loop,
        name="red-alert-scheduler",
        daemon=True,
    )
    _scheduler_thread.start()


def stop_scheduler() -> None:
    global _scheduler_stop_event, _scheduler_thread

    if _scheduler_stop_event is not None:
        _scheduler_stop_event.set()

    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        _scheduler_thread.join(timeout=5)

    _scheduler_stop_event = None
    _scheduler_thread = None
