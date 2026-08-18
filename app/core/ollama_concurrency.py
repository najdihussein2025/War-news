from __future__ import annotations

import asyncio
import threading

from app.core.config import settings

_ollama_thread_semaphore: threading.Semaphore | None = None


def get_ollama_thread_semaphore() -> threading.Semaphore:
    """Process-wide limit for concurrent Ollama calls (safe across event loops/threads)."""
    global _ollama_thread_semaphore
    if _ollama_thread_semaphore is None:
        _ollama_thread_semaphore = threading.Semaphore(
            max(1, settings.ollama_max_concurrent_requests)
        )
    return _ollama_thread_semaphore


def _run_under_semaphore(func, /, *args, **kwargs):
    with get_ollama_thread_semaphore():
        return func(*args, **kwargs)


async def run_with_ollama_limit(func, /, *args, **kwargs):
    """Run a blocking Ollama call in a worker thread under the shared semaphore."""
    return await asyncio.to_thread(_run_under_semaphore, func, *args, **kwargs)
