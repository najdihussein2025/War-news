"""The read-only 'is this a real summary bulletin' decision shared by audits and snapshots."""
from __future__ import annotations

from .detection import detect_summary
from .lexicon import LEXICON
from .parser import parse_summary
from .window import resolve_window


def accepted_parse(raw, gazetteer, headers):
    """Same detect + false-positive guard as ``intake_summary``, without any write.

    Returns ``(window, parse_result)`` for a real summary, otherwise ``None``.
    """
    body = raw.raw_text or ""
    if not detect_summary(body).is_summary:
        return None
    posted = raw.message_datetime or raw.received_at
    window = resolve_window(body, posted)
    result = parse_summary(body, gazetteer, headers, LEXICON, window.anchor_date)
    recognized = [header for header in result.headers if header.status == "approved"]
    if len(result.items) + len(result.unresolved_places) < 2 or not recognized:
        return None
    return window, result
