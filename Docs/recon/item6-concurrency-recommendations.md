# Item 6 — LLM concurrency recommendations (defaults unchanged)

Benchmarks run against `http://192.168.40.25:11435/ollama`, model `qwen2.5:7b`,
current production path (2-call Tier 1, per-category Tier 2, items 4–5 **disabled**).

## Parallel probe (presence-gate single call, n=4)

```
sequential_total=118.85s  concurrent_wall=33.07s  ratio=0.28
per_call concurrent: [28.64, 31.59, 30.12, 33.04]s
```

Server runs ~4 presence-gate requests in parallel without serial queuing.

## Full Tier-1 batch throughput (2 LLM calls/message)

| Config | Workers | Pool limit | n | mean/call | batch throughput |
|--------|---------|------------|---|-----------|------------------|
| item1-baseline | 2 | 2 (shared) | 10 | 66.30s | **1.78 msg/min** |
| item6-w4 | 4 | 2 | 5 | 97.74s | 1.50 msg/min |
| item6-pools4-w4 | 4 | 4 | 5 | 100.44s | 1.59 msg/min |

**Interpretation:** With pool=2, raising workers to 4 **hurts** throughput (workers block on
the 2-slot gate). With pool=4, throughput recovers slightly but per-call mean latency rises
~51% vs the w=2 baseline (66s → 100s) — soft saturation at 4 concurrent full Tier-1 pipelines.

## Proposed env overrides (not applied to code defaults)

| Setting | Current default | Proposed | Rationale |
|---------|-----------------|----------|-----------|
| `TIER1_LLM_MAX_CONCURRENT_REQUESTS` | 2 | **3** | Below observed latency knee (~4); preserves headroom |
| `TIER2_LLM_MAX_CONCURRENT_REQUESTS` | 2 | **4** | Separate pool; avg 0.43 categories/msg, lighter than Tier 1 |

Apply via `.env` after review — **code defaults remain 2/2** until items 4–5 are evaluated
and migration `20260902_0044` is applied.

## 300 msg/hour target

Current measured Tier-1 throughput ~1.8 msg/min (~108/hour) at concurrency 2.
Reaching 300/hour requires combined gains from: raised Tier-1 concurrency (~3), separated
Tier-2 pool, optional items 4–5 call collapsing, and pre-dedup index (item 2 migration).

Re-verify after enabling proposed env vars:

```bash
docker compose exec \
  -e TIER1_LLM_MAX_CONCURRENT_REQUESTS=3 \
  -e TIER2_LLM_MAX_CONCURRENT_REQUESTS=4 \
  backend python scripts/phase2-extraction-live-check/benchmark_tier1_batch_throughput.py \
  --workers 3 --ids 2604 2605 2606 2607 2608 2609 2610
```
