"""One-off probe: Ollama sequential vs concurrent latency for extraction-like calls."""
from __future__ import annotations

import asyncio
import statistics
import time

import httpx

BASE = "http://192.168.40.25:11435/ollama"
HEADERS = {"Authorization": "Bearer 8621398169a544929ec042986c11ce71"}
MODEL = "qwen2.5:7b"
TEXT = (
    "قصف مدفعي على بلدة كفركلا في جنوب لبنان، أدى إلى استشهاد مدني "
    "وإصابة اثنين. اندلاع حريق في مبنى سكني."
)
GENERAL_PROMPT = """Extract general fields from Arabic incident text. Return JSON only:
{"is_relevant": true, "village": ["..."], "action_description": "...",
 "casualties": {"total_deaths": null, "total_injuries": null, "deaths": null, "injuries": null,
 "male_deaths": null, "male_injuries": null, "female_deaths": null, "female_injuries": null,
 "children_deaths": null, "children_injuries": null}}"""


async def one_call(client: httpx.AsyncClient) -> float:
    payload = {
        "model": MODEL,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": GENERAL_PROMPT},
            {"role": "user", "content": TEXT},
        ],
        "options": {"temperature": 0.1},
    }
    t0 = time.perf_counter()
    response = await client.post("api/chat", json=payload)
    response.raise_for_status()
    return time.perf_counter() - t0


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, headers=HEADERS, timeout=120) as client:
        seq: list[float] = []
        for _ in range(4):
            seq.append(await one_call(client))
        print(
            "SEQUENTIAL (4 calls):",
            [round(x, 2) for x in seq],
            "total",
            round(sum(seq), 2),
            "avg",
            round(statistics.mean(seq), 2),
        )

        for n in (2, 4, 6, 8):
            t0 = time.perf_counter()
            times = await asyncio.gather(*[one_call(client) for _ in range(n)])
            wall = time.perf_counter() - t0
            print(
                f"CONCURRENT n={n}: wall={wall:.2f}s "
                f"per_call={[round(x, 2) for x in times]} "
                f"avg={statistics.mean(times):.2f} max={max(times):.2f}"
            )


if __name__ == "__main__":
    asyncio.run(main())
