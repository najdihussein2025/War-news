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
    args = parser.parse_args()

    samples = _load_samples(args.ids)
    model = args.model or settings.extraction_ollama_model

    print(f"Label: {args.label}")
    print(f"Ollama base URL: {settings.ollama_base_url}")
    print(f"Model: {model}")
    print(f"App-side max concurrent (env): {settings.ollama_max_concurrent_requests}")
    print(f"Benchmark workers: {args.workers}")
    print(f"Sample count: {len(samples)}")
    print(f"Sample IDs: {[s.raw_message_id for s in samples]}")

    if args.probe:
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
