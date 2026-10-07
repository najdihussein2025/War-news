from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .dtos import SummaryWindow
from .normalize import normalize_summary_text

BEIRUT = ZoneInfo("Asia/Beirut")
_HOURS = {"واحده":1,"الاولي":1,"ثانيه":2,"الثانيه":2,"ثالثه":3,"الثالثه":3,"رابعه":4,"الرابعه":4,"خامسه":5,"الخامسه":5,"سادسه":6,"السادسه":6,"سابعه":7,"السابعه":7,"ثامنه":8,"الثامنه":8,"تاسعه":9,"التاسعه":9,"عاشره":10,"العاشره":10,"حاديه عشره":11,"الحاديه عشره":11,"ثانيه عشره":12,"الثانيه عشره":12}


def _local(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("posted_at must be timezone-aware")
    return value.astimezone(BEIRUT)


def _clock(text: str, posted: datetime, anchor, start: datetime) -> tuple[datetime | None, str | None]:
    match = re.search(r"حتي\s+(?:الساعه\s*)?(?:(\d{1,2})(?:[:٫](\d{1,2}))?|((?:ال)?[\u0600-\u06ff]+(?:\s+عشره)?))(?:\s*(و\s*النصف|و\s*الربع|الا\s*ربع))?(?:\s*(صباحا|فجرا|ظهرا|عصرا|مساء|ليلا))?", text)
    if not match:
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
    if period in {"عصرا","مساء"} and hour < 12: hour += 12
    elif period == "ظهرا" and 1 <= hour <= 3: hour += 12
    elif period == "ليلا":
        if hour == 12: hour = 0
        elif 6 <= hour <= 11: hour += 12
    candidates = [datetime.combine(anchor, time(hour % 24, minute), BEIRUT)]
    if not period and hour <= 11:
        candidates.append(datetime.combine(anchor, time(hour + 12, minute), BEIRUT))
    valid = [c for c in candidates if c >= start and c <= posted + timedelta(minutes=15)]
    return (max(valid) if valid else None), match.group(0)


def resolve_window(text: str, posted_at: datetime, previous_summary_end: datetime | None = None) -> SummaryWindow:
    posted = _local(posted_at)
    normalized = re.sub(r"\s+", " ", normalize_summary_text(text).text)
    anchor = posted.date() - timedelta(days=1) if posted.hour < 3 else posted.date()
    explicit = re.search(r"بتاريخ\s+(\d{1,2})\s*[/.-]\s*(\d{1,2})(?:\s*[/.-]\s*(\d{2,4}))?", normalized)
    if explicit:
        year = int(explicit.group(3)) if explicit.group(3) else posted.year
        if year < 100: year += 2000
        candidate = datetime(year, int(explicit.group(2)), int(explicit.group(1)), tzinfo=BEIRUT)
        if not explicit.group(3) and candidate > posted: candidate = candidate.replace(year=year-1)
        end = posted if candidate.date() == posted.date() else candidate + timedelta(days=1)
        return SummaryWindow(candidate, end, "explicit_date", explicit.group(0), candidate.date())
    start = datetime.combine(anchor, time.min, BEIRUT)
    if re.search(r"خلال\s+(?:ال)?24\s+ساعه\s+الماضيه", normalized):
        return SummaryWindow(posted-timedelta(hours=24), posted, "last_24_hours", "24 ساعة", anchor)
    overnight = re.search(r"منذ\s+ليل\s+امس|بعد\s+الساعه\s+12\s+ليلا|من(?:ذ)?\s+(?:ما\s+)?منتصف\s+الليل", normalized)
    incremental = re.search(r"(?:الي|حتي|لغايه)\s+الان", normalized)
    broad = re.search(r"منذ\s+الصباح|خلال\s+الساعات\s+الماضيه|منذ\s+ساعات", normalized)
    if incremental and previous_summary_end is not None:
        prior = _local(previous_summary_end)
        if prior.date() == anchor:
            start = prior
    end, clock_evidence = _clock(normalized, posted, anchor, start)
    ignored = clock_evidence is not None and end is None
    if end is None: end = posted
    if overnight: rule = "overnight"
    elif incremental: rule = "incremental"
    elif broad: rule = "broad_partial"
    else: rule = "default"
    if ignored: rule += ":end_time_ignored"
    return SummaryWindow(start, end, rule, clock_evidence or (incremental.group(0) if incremental else None), anchor)
