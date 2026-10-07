from __future__ import annotations

import re

from .dtos import SummaryDetection
from .normalize import normalize_summary_text

_ACTION = r"(?:غار|غارات|قصف|تفجير|تفجيرات|قنابل|تمشيط|غالونات|طيران|مسير|فوسفور|مدفعي)"
_MARKERS = {
    "summary_topic": re.compile(r"(?<!\w)ملخص\s+(?:ال)?(?:اعتداءات|احداث)|(?<!\w)ملخص(?:\s+\S+){0,3}\s+لابرز"),
    "distributed_to_villages": re.compile(r"توزعت\s+علي\s+القري"),
    "summary_until_now": re.compile(r"ملخص\s+(?:الي|حتي)\s+الان"),
}


def detect_summary(text: str) -> SummaryDetection:
    normalized = normalize_summary_text(text).text
    flat = re.sub(r"\s+", " ", normalized)
    markers = tuple(name for name, pattern in _MARKERS.items() if pattern.search(flat))
    header_count = len(re.findall(rf"[^:\n]{{1,100}}{_ACTION}[^:\n]{{0,80}}\s*:", normalized))
    pieces = [p.strip() for p in re.split(r"[\n،,؛;]", normalized) if p.strip()]
    segment_count = sum(1 for p in pieces if not re.search(rf"{_ACTION}.*:$", p) and len(p.split()) <= 8)
    structural = header_count >= 2 and segment_count >= 6
    reasons = []
    if markers:
        reasons.append("marker")
    if structural:
        reasons.append("structural")
    return SummaryDetection(bool(markers or structural), markers, header_count, segment_count, tuple(reasons))
