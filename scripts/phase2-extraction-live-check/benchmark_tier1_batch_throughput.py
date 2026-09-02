"""Benchmark full Tier-1 extraction batch throughput (presence gate + general fields).

Use this for before/after OLLAMA_NUM_PARALLEL changes on the Ollama host.
Does not touch production pipeline code or DB writes.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.ollama_client import OllamaChatClient
from app.llm.services.ollama_extraction_service import OllamaExtractionService
from app.llm.services.ollama_presence_gate_service import OllamaPresenceGateService
from app.news.models import RawMessage

DEFAULT_SAMPLE_IDS = [
    692619,
    692621,
    692627,
    692631,
    692632,
    692635,
    692636,
    692637,
    692639,
    692640,
]


@dataclass(frozen=True)
class SampleMessage:
    raw_message_id: int
    post_text: str


def _stats(seconds: list[float]) -> dict[str, float]:
    ordered = sorted(seconds)
    n = len(ordered)
    mid = n // 2
    median = (
        ordered[mid]
        if n % 2 == 1
        else (ordered[mid - 1] + ordered[mid]) / 2
    )
    return {
        "n": float(n),
        "min": ordered[0],
        "max": ordered[-1],
        "mean": statistics.mean(ordered),
        "median": median,
    }


def _load_samples(ids: list[int]) -> list[SampleMessage]:
    with SessionLocal() as db:
        rows = list(
            db.scalars(select(RawMessage).where(RawMessage.id.in_(ids))).all()
        )
    by_id = {row.id: row for row in rows}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit(f"Missing raw_messages ids: {missing}")
    return [
        SampleMessage(raw_message_id=i, post_text=by_id[i].raw_text or "")
        for i in ids
    ]


def _build_service(model: str | None = None) -> OllamaExtractionService:
    client = OllamaChatClient(
        base_url=settings.ollama_base_url,
        api_key=settings.ollama_api_key,
        model=model or settings.extraction_ollama_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )
    return OllamaExtractionService(
        client=client,
        presence_gate=OllamaPresenceGateService(client),
    )


def _extract_one(service: OllamaExtractionService, sample: SampleMessage) -> tuple[int, float, bool]:
    started = time.monotonic()
    result = service.extract_tier1(
        sample.post_text,
        raw_message_id=sample.raw_message_id,
    )
    elapsed = time.monotonic() - started
    return sample.raw_message_id, elapsed, result.is_relevant


def _run_batch(
    samples: list[SampleMessage],
    *,
    workers: int,
    model: str | None,
    label: str,
) -> tuple[list[float], float]:
    print(f"\n=== {label} ({workers} worker(s), n={len(samples)}) ===")
    batch_started = time.monotonic()

    def _worker(sample: SampleMessage) -> tuple[int, float, bool]:
        # One httpx client / service per worker thread (httpx is not thread-safe).
        return _extract_one(_build_service(model), sample)

    if workers == 1:
        results = [_worker(sample) for sample in samples]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_worker, samples))
    batch_wall = time.monotonic() - batch_started

    timings = [elapsed for _, elapsed, _ in results]
    for raw_message_id, elapsed, is_relevant in results:
        print(
            f"  raw_message_id={raw_message_id} "
            f"elapsed={elapsed:.2f}s is_relevant={is_relevant}"
        )

    stats = _stats(timings)
    throughput = len(samples) / batch_wall * 60 if batch_wall > 0 else 0.0
    print(
        f"  per-call: min={stats['min']:.2f}s max={stats['max']:.2f}s "
        f"mean={stats['mean']:.2f}s median={stats['median']:.2f}s"
    )
    print(f"  batch_wall={batch_wall:.2f}s throughput={throughput:.2f} msg/min")
    return timings, batch_wall


def _run_parallel_probe(workers: int, model: str | None) -> None:
    """Quick single-call probe to infer whether Ollama runs requests in parallel."""
    from app.core.ollama_client import OllamaChatMessage
    from app.llm.services.ollama_presence_gate_service import (
        LOW_TEMPERATURE,
        PRESENCE_GATE_PROMPT,
        PRESENCE_GATE_RESPONSE_SCHEMA,
    )

    text = "مسيرة إسرائيلية ألقت قنبلة صوتية على بلدة المنصوري"

    def one_call() -> float:
        thread_client = OllamaChatClient(
            base_url=settings.ollama_base_url,
            api_key=settings.ollama_api_key,
            model=model or settings.extraction_ollama_model,
            timeout_seconds=settings.ollama_timeout_seconds,
        )
        started = time.monotonic()
        thread_client.chat(
            [
                OllamaChatMessage(role="system", content=PRESENCE_GATE_PROMPT),
                OllamaChatMessage(role="user", content=text),
            ],
            response_format=PRESENCE_GATE_RESPONSE_SCHEMA,
            temperature=LOW_TEMPERATURE,
        )
        return time.monotonic() - started

    seq_times = [one_call() for _ in range(workers)]
    seq_total = sum(seq_times)

    batch_started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        conc_times = list(pool.map(lambda _: one_call(), range(workers)))
    conc_wall = time.monotonic() - batch_started

    print(f"\n=== PARALLEL PROBE (presence-gate only, n={workers}) ===")
    print(f"  sequential_total={seq_total:.2f}s per_call={[round(t, 2) for t in seq_times]}")
    print(
        f"  concurrent_wall={conc_wall:.2f}s per_call={[round(t, 2) for t in conc_times]}"
    )
    ratio = conc_wall / seq_total if seq_total > 0 else 0.0
    print(f"  concurrent_wall / sequential_total = {ratio:.2f}")
    if ratio > 0.75:
        print(
            "  interpretation: requests appear mostly SERIAL on the server "
            "(concurrent wall ~ sum of singles). OLLAMA_NUM_PARALLEL may be 1."
        )
    elif ratio < 0.5:
        print(
            "  interpretation: server appears to run requests in PARALLEL "
            "(concurrent wall well below sequential sum)."
        )
    else:
        print(
            "  interpretation: partial parallelism or contention — "
            "compare before/after OLLAMA_NUM_PARALLEL change."
        )


def _run_tier_isolation_simulation(*, pool_limit: int) -> None:
    """Simulate Tier 2 saturation and measure Tier 1 start latency."""
    import asyncio
    import threading
    import time

    from app.core.ollama_concurrency import (
        run_with_ollama_limit,
        run_with_tier1_ollama_limit,
        run_with_tier2_ollama_limit,
    )
    import app.core.ollama_concurrency as ollama_concurrency_module

    tier2_hold_seconds = 1.0
    tier2_jobs = pool_limit * 2
    tier1_jobs = pool_limit * 2
    tier2_started = threading.Event()

    async def _shared_pool_scenario() -> float:
        """Legacy: one gate for both tiers (same limit value shares one semaphore)."""

        def tier2_work() -> None:
            tier2_started.set()
            time.sleep(tier2_hold_seconds)

        def tier1_work() -> None:
            time.sleep(0.01)

        async def saturate_tier2() -> None:
            await asyncio.gather(
                *[
                    run_with_ollama_limit(
                        tier2_work,
                        max_concurrent_requests=pool_limit,
                    )
                    for _ in range(tier2_jobs)
                ]
            )

        tier2_started.clear()
        tier2_task = asyncio.create_task(saturate_tier2())
        await asyncio.to_thread(tier2_started.wait, 1.0)
        started = time.monotonic()
        await asyncio.gather(
            *[
                run_with_ollama_limit(
                    tier1_work,
                    max_concurrent_requests=pool_limit,
                )
                for _ in range(tier1_jobs)
            ]
        )
        tier1_elapsed = time.monotonic() - started
        await tier2_task
        return tier1_elapsed

    async def _separated_pools_scenario() -> float:
        def tier2_work() -> None:
            tier2_started.set()
            time.sleep(tier2_hold_seconds)

        def tier1_work() -> None:
            time.sleep(0.01)

        async def saturate_tier2() -> None:
            await asyncio.gather(
                *[
                    run_with_tier2_ollama_limit(tier2_work)
                    for _ in range(tier2_jobs)
                ]
            )

        tier2_started.clear()
        tier2_task = asyncio.create_task(saturate_tier2())
        await asyncio.to_thread(tier2_started.wait, 1.0)
        started = time.monotonic()
        await asyncio.gather(
            *[
                run_with_tier1_ollama_limit(tier1_work)
                for _ in range(tier1_jobs)
            ]
        )
        tier1_elapsed = time.monotonic() - started
        await tier2_task
        return tier1_elapsed

    print(f"\n=== TIER POOL ISOLATION SIMULATION (pool_limit={pool_limit}) ===")
    ollama_concurrency_module._ollama_pool_semaphores.clear()
    shared_elapsed = asyncio.run(_shared_pool_scenario())
    ollama_concurrency_module._ollama_pool_semaphores.clear()
    separated_elapsed = asyncio.run(_separated_pools_scenario())
    print(
        f"  shared_pool tier1_batch_elapsed={shared_elapsed:.3f}s "
        f"(Tier 2 holds all {pool_limit} slots)"
    )
    print(
        f"  separated_pools tier1_batch_elapsed={separated_elapsed:.3f}s "
        f"(Tier 2 saturated on its own pool)"
    )
    if separated_elapsed < shared_elapsed * 0.75:
        print(
            "  interpretation: separated pools let Tier 1 proceed while Tier 2 "
            "is saturated (expected after item 1)."
        )
    else:
        print(
            "  interpretation: little difference — check pool wiring or increase "
            "tier2_hold_seconds."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark Tier-1 extraction batch throughput."
    )
    parser.add_argument(
        "--ids",
        nargs="*",
        type=int,
        default=DEFAULT_SAMPLE_IDS,
        help="raw_message ids (default: standard 10-ID benchmark set)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=settings.ollama_max_concurrent_requests,
        help="Concurrent extraction workers (default: OLLAMA_MAX_CONCURRENT_REQUESTS)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Ollama model override (default: EXTRACTION_OLLAMA_MODEL)",
    )
    parser.add_argument(
        "--label",
        default="run",
        help="Label printed in output (e.g. baseline-num-parallel-1, after-num-parallel-8)",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Also run a short presence-gate parallel probe before the batch",
    )
    parser.add_argument(
        "--sequential-baseline",
        action="store_true",
        help="Also run the same batch with 1 worker for comparison",
    )
    parser.add_argument(
        "--parallel-probe",
        action="store_true",
        help="Alias for --probe (presence-gate parallel probe)",
    )
    parser.add_argument(
        "--probe-only",
        action="store_true",
        help="Run parallel probe only (no DB sample batch)",
    )
    parser.add_argument(
        "--tier-isolation-test",
        action="store_true",
        help=(
            "Simulate Tier 2 saturation and compare Tier 1 latency under "
            "shared vs separated concurrency pools (no Ollama/DB required)"
        ),
    )
    args = parser.parse_args()

    if args.tier_isolation_test:
        pool_limit = max(1, settings.tier1_llm_max_concurrent_requests)
        print(f"Tier 1 pool limit: {settings.tier1_llm_max_concurrent_requests}")
        print(f"Tier 2 pool limit: {settings.tier2_llm_max_concurrent_requests}")
        _run_tier_isolation_simulation(pool_limit=pool_limit)
        return

    if args.probe_only or (
        (args.probe or args.parallel_probe)
        and args.label == "run"
        and not args.sequential_baseline
    ):
        print(f"Label: {args.label}")
        print(f"Ollama base URL: {settings.ollama_base_url}")
        print(f"Model: {args.model or settings.extraction_ollama_model}")
        _run_parallel_probe(args.workers, args.model)
        return

    samples = _load_samples(args.ids)
    model = args.model or settings.extraction_ollama_model

    print(f"Label: {args.label}")
    print(f"Ollama base URL: {settings.ollama_base_url}")
    print(f"Model: {model}")
    print(f"App-side max concurrent (env): {settings.ollama_max_concurrent_requests}")
    print(f"Tier 1 pool limit: {settings.tier1_llm_max_concurrent_requests}")
    print(f"Tier 2 pool limit: {settings.tier2_llm_max_concurrent_requests}")
    print(f"Benchmark workers: {args.workers}")
    print(f"Sample count: {len(samples)}")
    print(f"Sample IDs: {[s.raw_message_id for s in samples]}")

    if args.probe or args.parallel_probe:
        _run_parallel_probe(args.workers, args.model)

    if args.sequential_baseline:
        _run_batch(
            samples,
            workers=1,
            model=args.model,
            label=f"{args.label} — sequential",
        )

    _run_batch(
        samples,
        workers=args.workers,
        model=args.model,
        label=f"{args.label} — concurrent",
    )


if __name__ == "__main__":
    main()
