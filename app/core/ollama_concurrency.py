from __future__ import annotations

import asyncio
import threading
from typing import Literal

from app.core.config import settings

OllamaPool = Literal["default", "tier1", "tier2"]

_ollama_pool_semaphores: dict[str, threading.Semaphore] = {}


def _pool_limit(pool: OllamaPool) -> int:
    if pool == "tier1":
        return max(1, settings.tier1_llm_max_concurrent_requests)
    if pool == "tier2":
        return max(1, settings.tier2_llm_max_concurrent_requests)
    return max(1, settings.ollama_max_concurrent_requests)


def get_ollama_pool_semaphore(pool: OllamaPool = "default") -> threading.Semaphore:
    """Process-wide limit for concurrent Ollama calls in a named pool."""
    limit = _pool_limit(pool)
    cache_key = f"{pool}:{limit}"
    semaphore = _ollama_pool_semaphores.get(cache_key)
    if semaphore is None:
        semaphore = threading.Semaphore(limit)
        _ollama_pool_semaphores[cache_key] = semaphore
    return semaphore


def get_ollama_thread_semaphore(
    max_concurrent_requests: int | None = None,
) -> threading.Semaphore:
    """Legacy helper: default pool keyed by explicit limit (tests only)."""
    limit = max(
        1,
        max_concurrent_requests
        if max_concurrent_requests is not None
        else settings.ollama_max_concurrent_requests,
    )
    cache_key = f"default:{limit}"
    semaphore = _ollama_pool_semaphores.get(cache_key)
    if semaphore is None:
        semaphore = threading.Semaphore(limit)
        _ollama_pool_semaphores[cache_key] = semaphore
    return semaphore


def _run_under_pool_semaphore(
    func,
    /,
    *args,
    pool: OllamaPool = "default",
    **kwargs,
):
    with get_ollama_pool_semaphore(pool):
        return func(*args, **kwargs)


def _run_under_semaphore(func, /, *args, max_concurrent_requests: int | None = None, **kwargs):
    with get_ollama_thread_semaphore(max_concurrent_requests):
        return func(*args, **kwargs)


async def run_with_ollama_limit(
    func,
    /,
    *args,
    max_concurrent_requests: int | None = None,
    pool: OllamaPool | None = None,
    **kwargs,
):
    """Run a blocking Ollama call in a worker thread under a concurrency gate."""
    if pool is not None:
        return await asyncio.to_thread(
            _run_under_pool_semaphore,
            func,
            *args,
            pool=pool,
            **kwargs,
        )
    return await asyncio.to_thread(
        _run_under_semaphore,
        func,
        *args,
        max_concurrent_requests=max_concurrent_requests,
        **kwargs,
    )


async def run_with_tier1_ollama_limit(func, /, *args, **kwargs):
    """Run a blocking Tier 1 Ollama call under the Tier 1 concurrency gate."""
    return await run_with_ollama_limit(func, *args, pool="tier1", **kwargs)


async def run_with_tier2_ollama_limit(func, /, *args, **kwargs):
    """Run a blocking Tier 2 Ollama call under the Tier 2 concurrency gate."""
    return await run_with_ollama_limit(func, *args, pool="tier2", **kwargs)
