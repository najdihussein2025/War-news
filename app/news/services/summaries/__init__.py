"""Pure deterministic building blocks for summary-bulletin reconciliation."""

from .detection import detect_summary
from .parser import parse_summary
from .window import resolve_window
from .intake_service import intake_summary

__all__ = ["detect_summary", "parse_summary", "resolve_window", "intake_summary"]
