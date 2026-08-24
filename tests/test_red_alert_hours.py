from __future__ import annotations

from datetime import datetime, timezone

from app.core.scripts.run_red_alert_collector import (
    build_parser,
    collector_kwargs_for_hours,
)
from app.sources.services.red_alert_collector import HOURS_FETCH_LIMIT_CAP


def test_omitted_hours_keeps_default_fetch_limit() -> None:
    args = build_parser().parse_args([])
    assert args.hours is None
    assert args.once is False
    kwargs = collector_kwargs_for_hours(None)
    assert kwargs["min_message_datetime"] is None


def test_hours_raises_fetch_limit_and_sets_cutoff() -> None:
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    kwargs = collector_kwargs_for_hours(6, now=now)
    assert kwargs["fetch_limit"] == HOURS_FETCH_LIMIT_CAP
    assert kwargs["min_message_datetime"] == datetime(
        2026, 8, 24, 6, 0, tzinfo=timezone.utc
    )


def test_hours_and_once_parse() -> None:
    args = build_parser().parse_args(["--hours", "6", "--once"])
    assert args.hours == 6
    assert args.once is True
