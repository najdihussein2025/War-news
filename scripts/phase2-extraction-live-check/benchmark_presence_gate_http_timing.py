"""One-off presence-gate HTTP timing benchmark (not part of pipeline)."""
from __future__ import annotations

import argparse
import asyncio
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
from app.core.ollama_client import OllamaChatClient, OllamaChatMessage
from app.llm.services.ollama_presence_gate_service import (
    LOW_TEMPERATURE,
    PRESENCE_GATE_PROMPT,
    PRESENCE_GATE_RESPONSE_SCHEMA,
    OllamaPresenceGateService,
)
from app.news.models import MessageStatus, RawMessage


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


def _format_stats(label: str, seconds: list[float], *, batch_wall: float | None = None) -> str:
    stats = _stats(seconds)
    lines = [
        f"{label}:",
        f"  n={int(stats['n'])} min={stats['min']:.2f}s max={stats['max']:.2f}s "
        f"mean={stats['mean']:.2f}s median={stats['median']:.2f}s",
    ]
    if batch_wall is not None:
        lines.append(f"  batch_wall={batch_wall:.2f}s")
    return "\n".join(lines)


def _load_pending_messages(limit: int) -> list[SampleMessage]:
    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(RawMessage)
                .where(
                    RawMessage.status == MessageStatus.parsed,
                    RawMessage.extraction_result.is_(None),
                    RawMessage.duplicate_of_id.is_(None),
                )
                .order_by(RawMessage.id.asc())
                .limit(limit)
            ).all()
        )
    return [
        SampleMessage(raw_message_id=row.id, post_text=row.raw_text or "")
        for row in rows
    ]


def _build_client(model: str | None = None) -> OllamaChatClient:
    return OllamaChatClient(
        base_url=settings.ollama_base_url,
        api_key=settings.ollama_api_key,
        model=model or settings.extraction_ollama_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )


def _presence_gate_http_call(client: OllamaChatClient, post_text: str) -> str:
    """Same request shape as OllamaPresenceGateService.evaluate() before parsing."""
    return client.chat(
        [
            OllamaChatMessage(role="system", content=PRESENCE_GATE_PROMPT),
            OllamaChatMessage(role="user", content=post_text),
        ],
        response_format=PRESENCE_GATE_RESPONSE_SCHEMA,
        temperature=LOW_TEMPERATURE,
    )


def _timed_http_call(client: OllamaChatClient, sample: SampleMessage) -> tuple[float, str]:
    started = time.monotonic()
    content = _presence_gate_http_call(client, sample.post_text)
    elapsed = time.monotonic() - started
    return elapsed, content


def run_sequential(samples: list[SampleMessage], model: str | None = None) -> list[float]:
    client = _build_client(model)
    timings: list[float] = []
    for sample in samples:
        elapsed, _ = _timed_http_call(client, sample)
        timings.append(elapsed)
        print(
            f"  seq raw_message_id={sample.raw_message_id} "
            f"chars={len(sample.post_text)} elapsed={elapsed:.2f}s"
        )
    return timings


def run_concurrent(
    samples: list[SampleMessage],
    workers: int,
    model: str | None = None,
) -> tuple[list[float], float]:
    client = _build_client(model)

    def _worker(sample: SampleMessage) -> tuple[int, float]:
        elapsed, _ = _timed_http_call(client, sample)
        return sample.raw_message_id, elapsed

    batch_started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_worker, samples))
    batch_wall = time.monotonic() - batch_started

    timings = [elapsed for _, elapsed in results]
    for raw_message_id, elapsed in results:
        print(
            f"  conc raw_message_id={raw_message_id} elapsed={elapsed:.2f}s"
        )
    return timings, batch_wall


def run_accuracy_compare(
    samples: list[SampleMessage],
    models: list[str],
) -> None:
    baseline_model = settings.extraction_ollama_model
    baseline_results: dict[int, list[str]] = {}

    print("\n=== ACCURACY SPOT-CHECK (parsed categories) ===")
    for model in models:
        client = _build_client(model)
        service = OllamaPresenceGateService(client)
        print(f"\n--- model={model} ---")
        for sample in samples:
            started = time.monotonic()
            result = service.evaluate(
                sample.post_text,
                raw_message_id=sample.raw_message_id,
            )
            elapsed = time.monotonic() - started
            categories = [c.value for c in result.categories_present]
            print(
                f"raw_message_id={sample.raw_message_id} "
                f"elapsed={elapsed:.2f}s categories={categories}"
            )
            if model == baseline_model:
                baseline_results[sample.raw_message_id] = categories

    for model in models:
        if model == baseline_model:
            continue
        client = _build_client(model)
        service = OllamaPresenceGateService(client)
        print(f"\n--- disagreements vs {baseline_model} ({model}) ---")
        for sample in samples:
            result = service.evaluate(
                sample.post_text,
                raw_message_id=sample.raw_message_id,
            )
            categories = [c.value for c in result.categories_present]
            baseline = baseline_results.get(sample.raw_message_id, [])
            added = sorted(set(categories) - set(baseline))
            removed = sorted(set(baseline) - set(categories))
            if added or removed:
                snippet = sample.post_text[:120].replace("\n", " ")
                print(f"raw_message_id={sample.raw_message_id}")
                print(f"  text: {snippet}...")
                if added:
                    print(f"  +added vs baseline: {added}")
                if removed:
                    print(f"  -removed vs baseline: {removed}")


async def _fetch_ollama_tags() -> list[str]:
    client = _build_client()
    response = await client._async_client.get("api/tags")
    response.raise_for_status()
    payload = response.json()
    models = payload.get("models") or []
    names: list[str] = []
    for item in models:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(item["name"])
    return sorted(names)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--step",
        choices=("1", "2", "all"),
        default="1",
        help="1=HTTP timing only; 2=model compare; all=both",
    )
    parser.add_argument(
        "--models",
        nargs="*",
        default=None,
        help="Models for step 2 (must already exist on Ollama host)",
    )
    args = parser.parse_args()

    samples = _load_pending_messages(args.limit)
    if not samples:
        raise SystemExit("No pending parsed raw_messages found.")

    print(f"Ollama base URL: {settings.ollama_base_url}")
    print(f"Baseline model: {settings.extraction_ollama_model}")
    print(f"Timeout seconds: {settings.ollama_timeout_seconds}")
    print(f"Sample count: {len(samples)}")
    print("Sample IDs:", [s.raw_message_id for s in samples])
    print()

    if args.step in ("1", "all"):
        print("=== STEP 1: HTTP-only presence-gate timing ===")
        print("\nSequential (1 worker):")
        seq_timings = run_sequential(samples)
        print(_format_stats("Sequential stats", seq_timings))

        print(f"\nConcurrent ({args.workers} workers, 10 messages):")
        conc_timings, batch_wall = run_concurrent(samples, args.workers)
        print(_format_stats("Concurrent per-call stats", conc_timings, batch_wall=batch_wall))

    if args.step in ("2", "all"):
        available = asyncio.run(_fetch_ollama_tags())
        print("\nAvailable models on host:", available)
        models = args.models or [settings.extraction_ollama_model]
        unknown = [m for m in models if m not in available]
        if unknown:
            raise SystemExit(f"Requested models not on host: {unknown}")
        run_accuracy_compare(samples, models)


if __name__ == "__main__":
    main()
