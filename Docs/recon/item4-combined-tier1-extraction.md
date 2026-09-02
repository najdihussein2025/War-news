# Item 4 — Combined Tier-1 presence + general extraction (GATED OFF)

## Setting

`tier1_use_combined_presence_extraction` (env `TIER1_USE_COMBINED_PRESENCE_EXTRACTION`), default **false**.

## Prompt

`scripts/phase2-extraction-testing/combined_tier1_presence_extraction_instruction.txt`

Single JSON response merges presence gate fields (`categories_present`, `category_evidence`)
with general Tier-1 fields (`is_relevant`, `village`, `action_description`, `casualties`).
Downstream `extraction_result` shape unchanged.

## Evaluation (pilot n=5, answer_key samples 2–6)

Script: `scripts/phase2-extraction-live-check/compare_tier1_combined_vs_baseline.py`

| Metric | Baseline (2 calls) | Combined (1 call) |
|--------|-------------------|-------------------|
| LLM calls/msg | 2 | 1 (**50% reduction**) |
| Presence correct / missed / false_added | 0 / 6 / 0 | 0 / 6 / **4** |
| Casualties exact / mismatch | 0 / 2 | 0 / 2 |

**Do not enable yet.** Combined path adds false-positive presence categories on samples
3–6 (e.g. `lebanese_army`, `road_bridge`, `vehicles`) where baseline returned none, with
no recovery on missed categories.

Note: answer_key expected categories for samples 2–3 include labels not present in the
short `sample_*.txt` khabar snippets (e.g. hospital/government_building on sample 2’s
“غارة على بلدة تبنين”), so absolute recall vs answer_key is not the right gate — the
paired baseline vs combined delta is. On that delta, combined regresses on precision.

## Next step before enabling

Run full 43-sample comparison:

```bash
docker compose exec backend python scripts/phase2-extraction-live-check/compare_tier1_combined_vs_baseline.py
```

Review `scripts/phase2-extraction-testing/tier1_combined_comparison.json` and confirm
combined false_added ≤ baseline with no material recall drop.
