# Item 5 — Batched Tier-2 category detail extraction (GATED OFF)

## Setting

`tier2_use_batched_category_detail` (env `TIER2_USE_BATCHED_CATEGORY_DETAIL`), default **false**.

## Prompt

`scripts/phase2-extraction-testing/batched_category_detail_instruction.txt`

Single call accepts all flagged `category_keys` and returns `category_details[]` with the
same per-category field schema as the single-category path.

## Real-data call volume

From DB (`presence_category_keys` on 1,577 extracted rows):

- **Avg categories/message:** 0.43
- **Max:** 3

Expected call reduction when batching: ~57% at mean load; up to **67%** when 3 categories
(3 calls → 1).

## Evaluation (pilot n=2 category-rich samples)

Script: `compare_tier2_batched_vs_baseline.py --limit 2`

| Metric | Baseline | Batched |
|--------|----------|---------|
| LLM calls | 6 | 2 |
| Field-level agreement | 6/6 (100%) | same |

Both paths returned empty category details on samples 2–3 (short khabar text lacks
extractable did/name). Agreement is trivially perfect; run full category-rich subset
before enabling.

## Token budget / timeout

`extraction_llm_timeout_seconds` remains **240** (unchanged). Batched prompts grow with
category count; messages with many flagged categories may need a timeout bump — measure
on live backlog before enabling.

## Next step before enabling

```bash
docker compose exec backend python scripts/phase2-extraction-live-check/compare_tier2_batched_vs_baseline.py
```

Confirm field-level agreement ≥ baseline on samples where baseline produces non-empty details.
