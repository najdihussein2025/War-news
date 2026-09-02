# Item 1 — Separate Tier 1 / Tier 2 concurrency pools

## Problem

Both tiers shared one semaphore keyed only by `max_concurrent_requests` limit value
(`app/core/ollama_concurrency.py`). Tier 1 and Tier 2 both passed
`settings.extraction_llm_max_concurrent_requests` (default 2), so Tier 2 saturation
blocked Tier 1.

## Change

- Added `tier1_llm_max_concurrent_requests` and `tier2_llm_max_concurrent_requests`
  (env: `TIER1_LLM_MAX_CONCURRENT_REQUESTS`, `TIER2_LLM_MAX_CONCURRENT_REQUESTS`),
  default 2 each — same as the former shared limit.
- Named pools in `ollama_concurrency.py`: `run_with_tier1_ollama_limit()`,
  `run_with_tier2_ollama_limit()`.
- `pipeline_concurrent_sweeps.py` routes Tier 1 / Tier 2 through their respective gates
  and sizes worker counts from the matching setting.

## Benchmarks

### Live Tier 1 throughput (before, shared pool, limits=2)

```
Label: item1-baseline-shared-pool — concurrent (2 workers, n=10)
batch_wall=336.90s  throughput=1.78 msg/min
per-call mean=66.30s median=60.48s
```

After change: defaults unchanged (2/2), so live throughput is expected to match when
only Tier 1 is loaded. Isolation is the meaningful before/after metric below.

### Tier pool isolation simulation (`--tier-isolation-test`)

| Scenario | Tier 1 batch elapsed (Tier 2 saturated) |
|----------|-------------------------------------------|
| Shared pool (legacy) | 2.021s |
| Separated pools | 0.021s |

Tier 1 is no longer blocked when Tier 2 holds all slots on its own pool.
