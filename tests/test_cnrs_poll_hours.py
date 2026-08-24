from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.sources.actions.ingest_source_action import IngestSourceAction
from scripts.cnrs_poll_worker import (
    CnrsPollBootstrapRequired,
    build_parser,
    main,
    min_datetime_from_hours,
    _resolve_resume_cursor,
)


def test_hours_without_after_id_parses() -> None:
    args = build_parser().parse_args(["--hours", "6"])
    assert args.after_id is None
    assert args.hours == 6


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


class _FakeRepo:
    pass


def test_resolve_resume_cursor_uses_db_max_when_no_override(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.cnrs_poll_worker._last_ingested_cursor",
        lambda repo, source_id: "730500",
    )
    assert _resolve_resume_cursor(_FakeRepo(), 3, None) == "730500"


def test_resolve_resume_cursor_honors_explicit_override(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.cnrs_poll_worker._last_ingested_cursor",
        lambda repo, source_id: "730500",
    )
    assert _resolve_resume_cursor(_FakeRepo(), 3, "731000") == "731000"


def test_resolve_resume_cursor_raises_when_no_numeric_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.cnrs_poll_worker._last_ingested_cursor",
        lambda repo, source_id: None,
    )
    with pytest.raises(CnrsPollBootstrapRequired, match="--after-id"):
        _resolve_resume_cursor(_FakeRepo(), 3, None)


def test_main_exits_quietly_when_bootstrap_required(monkeypatch) -> None:
    def _raise_bootstrap(**kwargs):
        raise CnrsPollBootstrapRequired("bootstrap once with --after-id")

    monkeypatch.setattr("scripts.cnrs_poll_worker.run_poll_pass", _raise_bootstrap)
    main([])
