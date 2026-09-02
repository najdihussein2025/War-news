from __future__ import annotations

import asyncio
import threading
import time

import pytest

from app.core.config import settings
from app.core.ollama_concurrency import (
    get_ollama_pool_semaphore,
    get_ollama_thread_semaphore,
    run_with_ollama_limit,
    run_with_tier1_ollama_limit,
    run_with_tier2_ollama_limit,
)


def _reset_pool_semaphores() -> None:
    import app.core.ollama_concurrency as module

    module._ollama_pool_semaphores.clear()


@pytest.mark.asyncio
async def test_run_with_ollama_limit_caps_parallelism(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ollama_max_concurrent_requests", 2)
    _reset_pool_semaphores()

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


@pytest.mark.asyncio
async def test_tier1_and_tier2_pools_are_independent(monkeypatch) -> None:
    monkeypatch.setattr(settings, "tier1_llm_max_concurrent_requests", 2)
    monkeypatch.setattr(settings, "tier2_llm_max_concurrent_requests", 2)
    _reset_pool_semaphores()

    tier1_peak = 0
    tier2_peak = 0
    tier1_in_flight = 0
    tier2_in_flight = 0
    lock = threading.Lock()
    tier2_started = threading.Event()

    def tier2_work() -> None:
        nonlocal tier2_in_flight, tier2_peak
        with lock:
            tier2_in_flight += 1
            tier2_peak = max(tier2_peak, tier2_in_flight)
        tier2_started.set()
        time.sleep(0.2)
        with lock:
            tier2_in_flight -= 1

    def tier1_work() -> None:
        nonlocal tier1_in_flight, tier1_peak
        with lock:
            tier1_in_flight += 1
            tier1_peak = max(tier1_peak, tier1_in_flight)
        time.sleep(0.05)
        with lock:
            tier1_in_flight -= 1

    async def saturate_tier2() -> None:
        await asyncio.gather(
            *[
                run_with_tier2_ollama_limit(tier2_work)
                for _ in range(4)
            ]
        )

    tier2_task = asyncio.create_task(saturate_tier2())
    await asyncio.to_thread(tier2_started.wait, 0.5)

    await asyncio.gather(
        *[run_with_tier1_ollama_limit(tier1_work) for _ in range(4)]
    )
    await tier2_task

    assert tier1_peak == 2
    assert tier2_peak == 2
    assert get_ollama_pool_semaphore("tier1")._value <= 2  # type: ignore[attr-defined]
    assert get_ollama_pool_semaphore("tier2")._value <= 2  # type: ignore[attr-defined]
