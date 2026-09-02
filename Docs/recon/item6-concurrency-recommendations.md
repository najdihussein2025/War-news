# Item 6 - Tier-1 concurrency recommendation

Benchmarks use `http://192.168.40.25:11435/ollama`, model `qwen2.5:7b`, and the
two-call Tier-1 path. Code defaults remain unchanged.

| Configuration | Workers | Pool | n | Mean / median per call | Throughput | Result |
|---|---:|---:|---:|---|---:|---|
| item1 baseline | 2 | 2 | 10 | 66.30s / not recorded | **1.78 msg/min** | completed |
| item6 w4 | 4 | 2 | 5 | 97.74s / not recorded | 1.50 msg/min | completed |
| item6 pools4-w4 | 4 | 4 | 5 | 100.44s / not recorded | 1.59 msg/min | completed |
| pool3 fallback rerun | 3 | 3 | 10 | not available | not available | incomplete |

## Pool-3 attempt

The original standard IDs (`692619`, `692621`, `692627`, `692631`, `692632`,
`692635`, `692636`, `692637`, `692639`, `692640`) no longer exist in the local
database. I used the closest available current range, `2616` through `2625`,
with `TIER1_LLM_MAX_CONCURRENT_REQUESTS=3` and `--workers 3`.

Two executions were started. The first command stream detached before completion.
The second captured run produced the benchmark header and one model-validation
line but did not finish the 10-message batch during the bounded observation
window, so it produced no mean, median, wall time, or throughput. Those numbers
are deliberately recorded as unavailable rather than estimated.

## Server-side sanity check

The authenticated read-only `/api/ps` endpoint confirmed that `qwen2.5:7b` was
loaded. It exposed no queue depth or utilization metric and reported `size_vram: 0`.
The app-side benchmark workers spent their time waiting on inference/network I/O,
but that alone cannot establish whether the Ollama process is saturated, queued,
or blocked elsewhere.

## Verdict

**Stay at 2.** Pool 4 is measured slower than the pool-2 baseline, and pool 3
has no completed comparable measurement. Do not raise Tier-1 concurrency or
recommend 3/4. The likely constraint is outside the application semaphore, but
single-Ollama saturation is not confirmed by the available server metrics.
