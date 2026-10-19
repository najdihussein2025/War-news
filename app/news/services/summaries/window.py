from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .dtos import SummaryWindow
from .normalize import normalize_summary_text

BEIRUT = ZoneInfo("Asia/Beirut")
MIN_DAILY_WINDOW = timedelta(hours=3)
_HOURS = {"واحده":1,"الاولي":1,"ثانيه":2,"الثانيه":2,"ثالثه":3,"الثالثه":3,"رابعه":4,"الرابعه":4,"خامسه":5,"الخامسه":5,"سادسه":6,"السادسه":6,"سابعه":7,"السابعه":7,"ثامنه":8,"الثامنه":8,"تاسعه":9,"التاسعه":9,"عاشره":10,"العاشره":10,"حاديه عشره":11,"الحاديه عشره":11,"ثانيه عشره":12,"الثانيه عشره":12}
# "until 12:00 at night" / "until midnight" closes the day at 24:00, not at 00:00 of the same day.
_END_OF_DAY = re.compile(r"(?:حتي|لغايه)\s+(?:الساعه\s+)?(?:منتصف\s+الليل|(?:12|الثانيه\s+عشره)(?:[:٫]00?)?\s*ليلا)")
_INCREMENTAL = re.compile(r"(?:الي|حتي|لغايه)\s+الان")


def _local(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("posted_at must be timezone-aware")
    return value.astimezone(BEIRUT)


def _clock(text: str, posted: datetime, anchor, start: datetime) -> tuple[datetime | None, str | None]:
    match = re.search(r"حتي\s+(?:الساعه\s*)?(?:(\d{1,2})(?:[:٫](\d{1,2}))?|((?:ال)?[؀-ۿ]+(?:\s+عشره)?))(?:\s*(و\s*النصف|و\s*الربع|الا\s*ربع))?(?:\s*(صباحا|فجرا|ظهرا|عصرا|مساء|ليلا))?", text)
    if not match:
        return None, None
    if match.group(3) and match.group(3).strip() == "الان":
        return None, None
    if match.group(1):
        hour, minute = int(match.group(1)), int(match.group(2) or 0)
    else:
        word = (match.group(3) or "").strip()
        hour = _HOURS.get(word, 0); minute = 0
        if not hour:
            return None, match.group(0)
    fraction = (match.group(4) or "").replace(" ", "")
    if "النصف" in fraction: minute = 30
    elif "الربع" in fraction: minute = 15
    elif "الاربع" in fraction or "الاربع" in fraction: minute = 45; hour = (hour - 1) % 24
    period = match.group(5)
    shift = 0
    if period in {"عصرا","مساء"} and hour < 12: hour += 12
    elif period == "ظهرا" and 1 <= hour <= 3: hour += 12
    elif period == "ليلا":
        if hour == 12: hour = 0; shift = 1
        elif 6 <= hour <= 11: hour += 12
    day = anchor + timedelta(days=shift)
    candidates = [datetime.combine(day, time(hour % 24, minute), BEIRUT)]
    if not period and hour <= 11:
        candidates.append(datetime.combine(day, time(hour + 12, minute), BEIRUT))
    valid = [c for c in candidates if c >= start and c <= posted + timedelta(minutes=15)]
    return (max(valid) if valid else None), match.group(0)


def _finalize(window: SummaryWindow, *, daily: bool) -> SummaryWindow:
    """Flag windows that cannot be trusted: zero/negative length, or a daily summary under 3h."""
    length = window.end - window.start
    invalid = length <= timedelta(0) or (daily and length < MIN_DAILY_WINDOW)
    return replace(window, window_invalid=True) if invalid else window


def resolve_window(text: str, posted_at: datetime, previous_summary_end: datetime | None = None) -> SummaryWindow:
    posted = _local(posted_at)
    normalized = re.sub(r"\s+", " ", normalize_summary_text(text).text)
    anchor = posted.date() - timedelta(days=1) if posted.hour < 3 else posted.date()
    incremental = _INCREMENTAL.search(normalized)
    explicit = re.search(r"بتاريخ\s+(\d{1,2})\s*[/.-]\s*(\d{1,2})(?:\s*[/.-]\s*(\d{2,4}))?", normalized)
    if explicit:
        year = int(explicit.group(3)) if explicit.group(3) else posted.year
        if year < 100: year += 2000
        candidate = datetime(year, int(explicit.group(2)), int(explicit.group(1)), tzinfo=BEIRUT)
        if not explicit.group(3) and candidate > posted: candidate = candidate.replace(year=year-1)
        delta=(anchor-candidate.date()).days
        if candidate.date() > posted.date():
            start=datetime.combine(posted.date(),time.min,BEIRUT)
            return _finalize(SummaryWindow(start,posted,"explicit_date:future_ignored",explicit.group(0),posted.date(),"future_date_ignored","fallback"), daily=False)
        if candidate.date() == posted.date() and posted.hour < 3 and not incremental:
            # A daily summary posted 00:00-03:00 that carries the posting date is the previous
            # day's report (the channel stamps the new date at midnight).
            previous = candidate - timedelta(days=1)
            return _finalize(SummaryWindow(previous, candidate, "explicit_date:posted_after_midnight", explicit.group(0), previous.date(), "stated_date_is_posting_date_after_midnight", "regex_explicit"), daily=True)
        # Staleness is measured against the anchor day, not the posting date: a
        # 00:00:51 post on 17/9 summarises 16/9, so a 15/9 header is one day old.
        if delta == 1:
            # Content is the anchor day's; timed events must land on that day.
            return _finalize(SummaryWindow(candidate,posted,"explicit_date:stale_suspect",explicit.group(0),anchor,"stale_explicit_date","regex_explicit"), daily=False)
        end = posted if candidate.date() == posted.date() else candidate + timedelta(days=1)
        return _finalize(SummaryWindow(candidate, end, "explicit_date", explicit.group(0), candidate.date(),"old_summary_reshared" if delta>=2 else None, "regex_explicit"), daily=True)
    start = datetime.combine(anchor, time.min, BEIRUT)
    if re.search(r"خلال\s+(?:ال)?24\s+ساعه\s+الماضيه", normalized):
        return _finalize(SummaryWindow(posted-timedelta(hours=24), posted, "last_24_hours", "24 ساعة", anchor, None, "regex_relative"), daily=False)
    overnight = re.search(r"منذ\s+ليل\s+امس|بعد\s+الساعه\s+12\s+ليلا|من(?:ذ)?\s+(?:ما\s+)?منتصف\s+الليل", normalized)
    broad = re.search(r"منذ\s+الصباح|خلال\s+الساعات\s+الماضيه|منذ\s+ساعات", normalized)
    if incremental and previous_summary_end is not None:
        prior = _local(previous_summary_end)
        if prior.date() == anchor:
            start = prior
    end_of_day = _END_OF_DAY.search(normalized)
    closing = datetime.combine(anchor + timedelta(days=1), time.min, BEIRUT)
    if end_of_day and closing <= posted + timedelta(minutes=15):
        end, clock_evidence = closing, end_of_day.group(0)
        end_marker = ":end_of_day"
    else:
        end, clock_evidence = _clock(normalized, posted, anchor, start)
        end_marker = ""
    ignored = clock_evidence is not None and end is None
    explicit_end = end is not None
    if end is None: end = posted
    if overnight: rule = "overnight"
    elif incremental: rule = "incremental"
    elif broad: rule = "broad_partial"
    else: rule = "default"
    rule += end_marker
    if ignored: rule += ":end_time_ignored"
    if explicit_end:
        source = "regex_explicit"
    elif overnight or incremental or broad:
        source = "regex_relative"
    else:
        source = "fallback"
    daily = rule.split(":")[0] in {"overnight", "default"} and not incremental and not broad
    return _finalize(SummaryWindow(start, end, rule, clock_evidence or (incremental.group(0) if incremental else None), anchor, None, source), daily=daily)
