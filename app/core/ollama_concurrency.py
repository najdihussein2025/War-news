from __future__ import annotations

import asyncio
import threading

from app.core.config import settings

_ollama_thread_semaphores: dict[int, threading.Semaphore] = {}


def get_ollama_thread_semaphore(
    max_concurrent_requests: int | None = None,
) -> threading.Semaphore:
    """Process-wide limit for concurrent Ollama calls (safe across event loops/threads)."""
    limit = max(
        1,
        max_concurrent_requests
        if max_concurrent_requests is not None
        else settings.ollama_max_concurrent_requests,
    )
    semaphore = _ollama_thread_semaphores.get(limit)
    if semaphore is None:
        semaphore = threading.Semaphore(limit)
        _ollama_thread_semaphores[limit] = semaphore
    return semaphore


def _run_under_semaphore(func, /, *args, max_concurrent_requests: int | None = None, **kwargs):
    with get_ollama_thread_semaphore(max_concurrent_requests):
        return func(*args, **kwargs)


async def run_with_ollama_limit(
    func,
    /,
    *args,
    max_concurrent_requests: int | None = None,
    **kwargs,
):
    """Run a blocking Ollama call in a worker thread under the shared semaphore."""
    return await asyncio.to_thread(
        _run_under_semaphore,
        func,
        *args,
        max_concurrent_requests=max_concurrent_requests,
        **kwargs,
    )
