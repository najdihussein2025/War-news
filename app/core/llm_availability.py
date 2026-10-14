"""Process-local circuit breaker for the optional Ollama dependency.

The breaker deliberately only treats transport failures as an outage.  A model
answer that is malformed remains a normal pipeline failure and is handled by
the stage-specific retry policy.
"""
from __future__ import annotations

import threading
import time

import httpx

from app.core.config import settings


class LLMUnavailableError(RuntimeError):
    """Raised without making a generation request while the circuit is open."""


def is_llm_connection_error(exc: BaseException) -> bool:
    return isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError))


class LLMAvailability:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._offline_since: float | None = None
        self._last_check: float = 0.0

    @property
    def offline_since(self) -> float | None:
        with self._lock:
            return self._offline_since

    def mark_unavailable(self) -> None:
        with self._lock:
            self._offline_since = self._offline_since or time.time()
            self._last_check = time.monotonic()

    def mark_available(self) -> None:
        with self._lock:
            self._offline_since = None
            self._last_check = time.monotonic()

    def permit_request(self) -> bool:
        """Return false while open; periodically probe once for recovery."""
        with self._lock:
            if self._offline_since is None:
                return True
            if time.monotonic() - self._last_check < settings.llm_health_recheck_seconds:
                return False
            self._last_check = time.monotonic()
        try:
            # tags is lightweight and does not load/run a model.
            response = httpx.get(
                f"{settings.ollama_base_url.rstrip('/')}/api/tags",
                timeout=settings.llm_connect_timeout_seconds,
                headers={"Authorization": f"Bearer {settings.ollama_api_key}"}
                if settings.ollama_api_key else None,
            )
            response.raise_for_status()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError):
            return False
        self.mark_available()
        return True


llm_availability = LLMAvailability()
