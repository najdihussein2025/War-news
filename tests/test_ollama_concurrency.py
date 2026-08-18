from __future__ import annotations

import asyncio
import threading
import time

import pytest

from app.core.config import settings
from app.core.ollama_concurrency import get_ollama_thread_semaphore, run_with_ollama_limit


@pytest.mark.asyncio
async def test_run_with_ollama_limit_caps_parallelism(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ollama_max_concurrent_requests", 2)
    import app.core.ollama_concurrency as module

    module._ollama_thread_semaphore = threading.Semaphore(2)

    in_flight = 0
    peak = 0
    lock = threading.Lock()

    def blocking_work() -> None:
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(0.05)
        with lock:
            in_flight -= 1

    await asyncio.gather(
        *[run_with_ollama_limit(blocking_work) for _ in range(6)]
    )

    assert peak <= 2
    assert get_ollama_thread_semaphore()._value <= 2  # type: ignore[attr-defined]
