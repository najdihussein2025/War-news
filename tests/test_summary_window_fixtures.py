"""Window resolution against real summary texts (tests/fixtures/summaries/{raw_message_id}.txt)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.news.services.summaries.window import resolve_window

TZ = ZoneInfo("Asia/Beirut")
FIXTURES = Path(__file__).parent / "fixtures" / "summaries"


def at(month: int, day: int, h: int, m: int = 0, s: int = 0) -> datetime:
    return datetime(2026, month, day, h, m, s, tzinfo=TZ)


# id: (posted_at, expected_start, expected_end, expected_source, expected_rule)
CASES = {
    # The four broken windows (old code: three zero-length 00:00->00:00, one 1-minute window).
    35286: (at(9, 21, 0, 12, 22), at(9, 20, 0), at(9, 21, 0), "regex_explicit", "overnight:end_of_day"),
    32708: (at(9, 8, 0, 50, 56), at(9, 7, 0), at(9, 8, 0), "regex_explicit", "overnight:end_of_day"),
    34700: (at(9, 19, 0, 21, 24), at(9, 18, 0), at(9, 19, 0), "regex_explicit", "overnight:end_of_day"),
    34698: (at(9, 19, 0, 1, 51), at(9, 18, 0), at(9, 19, 0), "regex_explicit", "explicit_date:posted_after_midnight"),
    # Normal summaries from other channels.
    36062: (at(9, 24, 0, 17, 38), at(9, 23, 0), at(9, 24, 0), "regex_explicit", "explicit_date"),
    35282: (at(9, 20, 23, 58, 5), at(9, 20, 0), at(9, 20, 23, 58, 5), "regex_explicit", "explicit_date"),
    36121: (at(9, 24, 10, 2, 22), at(9, 24, 0), at(9, 24, 9, 30), "regex_explicit", "overnight"),
    29730: (at(8, 25, 0, 0, 12), at(8, 24, 0), at(8, 25, 0, 0, 12), "fallback", "default"),
    28539: (at(8, 25, 9, 24, 35), at(8, 25, 0), at(8, 25, 9, 24, 35), "regex_relative", "overnight"),
    28646: (at(8, 25, 23, 58, 32), at(8, 25, 0), at(8, 25, 23, 58, 32), "fallback", "default"),
}


def _text(message_id: int) -> str:
    return (FIXTURES / f"{message_id}.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("message_id", sorted(CASES))
def test_fixture_window(message_id: int) -> None:
    posted, start, end, source, rule = CASES[message_id]
    window = resolve_window(_text(message_id), posted)
    assert (window.start, window.end) == (start, end)
    assert window.rule == rule
    assert window.source == source
    assert window.window_invalid is False
    assert window.end > window.start


@pytest.mark.parametrize("message_id", [35286, 32708, 34700])
def test_end_of_night_marker_closes_the_day_at_midnight(message_id: int) -> None:
    posted = CASES[message_id][0]
    window = resolve_window(_text(message_id), posted)
    assert (window.end - window.start).total_seconds() == 86400
    assert window.anchor_date == window.start.date()


def test_daily_summary_posted_after_midnight_with_posting_date_is_previous_day() -> None:
    posted = CASES[34698][0]
    window = resolve_window(_text(34698), posted)
    assert window.anchor_date.isoformat() == "2026-09-18"
    assert window.note == "stated_date_is_posting_date_after_midnight"


def test_midnight_phrases_all_mean_end_of_day() -> None:
    posted = at(9, 21, 0, 12)
    for phrase in ("حتى الساعة ١٢:٠٠ ليلاً", "حتى الساعة ١٢ ليلاً", "حتى منتصف الليل"):
        window = resolve_window(f"ملخص الاعتداءات منذ ليل امس {phrase}", posted)
        assert window.end == at(9, 21, 0), phrase


def test_twelve_thirty_at_night_is_after_midnight_of_the_next_day() -> None:
    window = resolve_window("ملخص منذ ليل امس حتى الساعة ١٢:٣٠ ليلاً", at(9, 21, 0, 40))
    assert window.end == at(9, 21, 0, 30)


def test_zero_length_window_is_invalid() -> None:
    from dataclasses import replace

    from app.news.services.summaries.window import _finalize

    window = resolve_window("ملخص الاعتداءات حتى الساعة 12 ظهرا", at(9, 21, 12, 0))
    assert not window.window_invalid
    assert _finalize(replace(window, end=window.start), daily=False).window_invalid


def test_short_daily_window_is_invalid_but_short_partial_is_not() -> None:
    # Daily summary whose clock end lands 1h after the start of the day.
    daily = resolve_window("ملخص الاعتداءات منذ منتصف الليل حتى الساعة 1 صباحا", at(9, 21, 1, 5))
    assert daily.window_invalid
    partial = resolve_window("ملخص الى الان", at(9, 21, 8, 0), previous_summary_end=at(9, 21, 7, 0))
    assert not partial.window_invalid
