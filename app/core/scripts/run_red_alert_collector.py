from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging_config import configure_logging
from app.sources.services.red_alert_collector import (
    RedAlertCollector,
    fetch_limit_for_hours,
)

logger = logging.getLogger(__name__)


def _parse_hours_arg(value: str) -> int:
    try:
        hours = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--hours must be an integer >= 1.") from exc
    if hours < 1:
        raise argparse.ArgumentTypeError("--hours must be an integer >= 1.")
    return hours


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Poll Red Alert Lebanon and ingest air-violation posts."
    )
    parser.add_argument(
        "--hours",
        type=_parse_hours_arg,
        help=(
            "Only keep posts with message_datetime within the last N hours. "
            "Raises fetch_limit (capped) so the window can be reached."
        ),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single collect_once cycle and exit instead of looping.",
    )
    return parser


def collector_kwargs_for_hours(
    hours: int | None,
    *,
    now: datetime | None = None,
) -> dict:
    kwargs: dict = {
        "fetch_limit": settings.red_alert_fetch_limit,
        "min_message_datetime": None,
    }
    if hours is None:
        return kwargs
    current = now or datetime.now(timezone.utc)
    kwargs["fetch_limit"] = fetch_limit_for_hours(hours, settings.red_alert_fetch_limit)
    kwargs["min_message_datetime"] = current - timedelta(hours=hours)
    return kwargs


def collect_once_with_options(*, hours: int | None = None) -> dict[str, int]:
    extra = collector_kwargs_for_hours(hours)
    with SessionLocal() as db:
        return RedAlertCollector(
            db,
            delivery_method=settings.red_alert_delivery_method,
            channel_username=settings.red_alert_channel_username,
            fetch_limit=extra["fetch_limit"],
            request_timeout=settings.red_alert_request_timeout_seconds,
            ocr_enabled=settings.red_alert_ocr_enabled,
            min_message_datetime=extra["min_message_datetime"],
        ).collect_once()


def run_forever(*, hours: int | None = None) -> None:
    configure_logging()
    extra = collector_kwargs_for_hours(hours)
    logger.info(
        "Red Alert collector starting enabled=%s delivery_method=%s channel=@%s "
        "poll_seconds=%s ocr=%s fetch_limit=%s hours=%s",
        settings.red_alert_enabled,
        settings.red_alert_delivery_method,
        settings.red_alert_channel_username,
        settings.red_alert_poll_seconds,
        settings.red_alert_ocr_enabled,
        extra["fetch_limit"],
        hours,
    )
    while True:
        if settings.red_alert_enabled:
            try:
                result = collect_once_with_options(hours=hours)
                logger.info("Red Alert collection result=%s", result)
            except Exception:
                logger.exception("Red Alert collection cycle failed")
        time.sleep(max(10.0, settings.red_alert_poll_seconds))


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.once:
        configure_logging()
        result = collect_once_with_options(hours=args.hours)
        logger.info("Red Alert collection result=%s", result)
        return
    run_forever(hours=args.hours)


if __name__ == "__main__":
    main()
