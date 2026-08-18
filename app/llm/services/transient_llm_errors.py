from __future__ import annotations

import httpx


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
