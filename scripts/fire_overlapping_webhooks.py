"""Fire overlapping CNRS webhook bursts for concurrent pipeline verification."""
from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from datetime import datetime, timezone

import httpx

BASE_URL = os.environ.get("WEBHOOK_BASE_URL", "http://127.0.0.1:8000")
SECRET = os.environ["CNRS_WEBHOOK_SECRET"]
BATCH_SIZE = int(os.environ.get("WEBHOOK_BATCH_SIZE", "8"))

SAMPLES = [
    "قصف مدفعي على بلدة كفركلا في جنوب لبنان، أدى إلى إصابة مدني.",
    "غارة جوية استهدفت أطراف بلدة بنت جبيل دون وقوع ضحايا.",
    "إطلاق نار على بلدة عيتا الشعب في قضاء صور.",
    "قصف على بلدة حula في جنوب لبنان.",
    "استهداف بلدة رmeish بقذائف مدفعية.",
    "قصف على بلدة الخيام في قضاء مرجعيون.",
    "غارة على بلدة كفركلا.",
    "قصف مدفعي على بلدة عitaroun.",
    "إصابة مدني في بلدة تبنين جراء قصف.",
    "قصف على بلدة شحور.",
    "غارة على بلدة كفرشوبا.",
    "قصف على بلدة العديسة.",
]


def _payload(index: int, batch: int) -> dict:
    text = SAMPLES[index % len(SAMPLES)]
    return {
        "external_message_id": f"loadtest-{batch}-{index}-{uuid.uuid4().hex[:8]}",
        "message_datetime": datetime.now(timezone.utc).isoformat(),
        "raw_text": text,
        "source_platform": "telegram",
        "source_name": "load-test-channel",
        "include": True,
        "confidence": 0.95,
        "event_domain": "security",
        "event_subtype": "shelling",
    }


async def _post_batch(client: httpx.AsyncClient, batch: int) -> tuple[int, float]:
    payload = [_payload(i, batch) for i in range(BATCH_SIZE)]
    started = time.perf_counter()
    response = await client.post(
        "/webhooks/cnrs-posts",
        json=payload,
        headers={"X-Webhook-Secret": SECRET},
    )
    elapsed = time.perf_counter() - started
    response.raise_for_status()
    return batch, elapsed


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        print(f"Firing 2 overlapping webhook bursts of {BATCH_SIZE} messages each...")
        t0 = time.perf_counter()
        results = await asyncio.gather(
            _post_batch(client, batch=1),
            _post_batch(client, batch=2),
        )
        wall = time.perf_counter() - t0
        for batch, elapsed in results:
            print(f"  batch={batch} http_seconds={elapsed:.2f}")
        print(f"Both accepted in wall_seconds={wall:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
