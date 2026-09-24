from __future__ import annotations

import httpx

TRANSIENT_LLM_ERROR_MARKERS = (
    "readtimeout",
    "connecttimeout",
    "timeouterror",
    "timed out",
    "connection reset",
    "connection refused",
    "connecterror",
    "networkerror",
    "temporarily unavailable",
    "503",
    "502",
    "504",
)


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

    return any(marker in message for marker in TRANSIENT_LLM_ERROR_MARKERS)


class Tier2ExtractionFailedError(Exception):
    """Raised when a Tier-2 category detail LLM call fails (not an empty answer)."""

    def __init__(self, failed_categories: list[str], last_error: BaseException) -> None:
        self.failed_categories = failed_categories
        self.last_error = last_error
        super().__init__(
            f"tier2: failed categories={failed_categories} "
            f"last error: {format_llm_error(last_error)}"
        )
