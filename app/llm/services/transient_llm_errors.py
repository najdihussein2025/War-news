from __future__ import annotations

import httpx


class ExtractionRetryCappedError(Exception):
    """Raised when a transient extraction failure hits the retry cap."""


def format_llm_error(exc: BaseException) -> str:
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return f"{type(exc).__name__} (no message)"


def extraction_retry_cap_message(retry_count: int, exc: BaseException) -> str:
    return (
        f"extraction: exceeded max retries ({retry_count}) — "
        f"last error: {format_llm_error(exc)}"
    )


def is_transient_llm_error(exc: BaseException) -> bool:
    """Return True when the failure is likely retryable (timeout/network), not bad data."""
    if isinstance(exc, httpx.TimeoutException):
        return True

    message = str(exc).strip().lower()
    if not message:
        return False

    transient_markers = (
        "readtimeout",
        "connecttimeout",
        "timeouterror",
        "timed out",
        "connection reset",
        "connection refused",
        "temporarily unavailable",
        "503",
        "502",
        "504",
    )
    return any(marker in message for marker in transient_markers)
