from __future__ import annotations

import logging
import time

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging_config import configure_logging
from app.sources.services.red_alert_collector import RedAlertCollector

logger = logging.getLogger(__name__)


def run_forever() -> None:
    configure_logging()
    logger.info(
        "Red Alert collector starting enabled=%s delivery_method=%s channel=@%s poll_seconds=%s ocr=%s",
        settings.red_alert_enabled,
        settings.red_alert_delivery_method,
        settings.red_alert_channel_username,
        settings.red_alert_poll_seconds,
        settings.red_alert_ocr_enabled,
    )
    while True:
        if settings.red_alert_enabled:
            try:
                with SessionLocal() as db:
                    result = RedAlertCollector(
                        db,
                        delivery_method=settings.red_alert_delivery_method,
                        channel_username=settings.red_alert_channel_username,
                        fetch_limit=settings.red_alert_fetch_limit,
                        request_timeout=settings.red_alert_request_timeout_seconds,
                        ocr_enabled=settings.red_alert_ocr_enabled,
                    ).collect_once()
                logger.info("Red Alert collection result=%s", result)
            except Exception:
                logger.exception("Red Alert collection cycle failed")
        time.sleep(max(10.0, settings.red_alert_poll_seconds))


if __name__ == "__main__":
    run_forever()
