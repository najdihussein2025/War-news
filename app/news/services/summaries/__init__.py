"""Pure deterministic building blocks for summary-bulletin reconciliation."""

from .detection import detect_summary
from .parser import parse_summary
from .window import resolve_window

__all__ = ["detect_summary", "parse_summary", "resolve_window"]
