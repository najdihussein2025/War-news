from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.sources.actions.ingest_source_action import IngestSourceAction
from scripts.cnrs_poll_worker import (
    build_parser,
    main,
    min_datetime_from_hours,
)


def test_hours_flag_requires_after_id() -> None:
    with pytest.raises(SystemExit):
        main(["--hours", "6"])


def test_hours_and_after_id_parse() -> None:
    args = build_parser().parse_args(["--after-id", "731000", "--hours", "6"])
    assert args.after_id == "731000"
    assert args.hours == 6


def test_omitted_hours_keeps_after_id_optional() -> None:
    args = build_parser().parse_args([])
    assert args.after_id is None
    assert args.hours is None


def test_hours_cutoff_excludes_older_posts() -> None:
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    cutoff = min_datetime_from_hours(6, now=now)
    assert cutoff == datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc)
    assert IngestSourceAction._is_before_cutoff(
        datetime(2026, 8, 24, 5, 59, tzinfo=timezone.utc),
        cutoff,
    )
    assert not IngestSourceAction._is_before_cutoff(
        datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc),
        cutoff,
    )


def test_omitted_hours_does_not_apply_cutoff() -> None:
    assert min_datetime_from_hours(None) is None
    assert IngestSourceAction._is_before_cutoff(
        datetime(2020, 1, 1, tzinfo=timezone.utc),
        None,
    ) is False
