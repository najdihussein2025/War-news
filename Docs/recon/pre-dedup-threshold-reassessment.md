# Pre-extraction dedup threshold reassessment (2026-09-07)

## Current default

`pre_dedup_similarity_threshold = 0.92` (`word_similarity` on `raw_text`, same-source).

## Question

The Nabatiyeh/حي المسلخ same-event cluster had a best peer pair at **0.8627**,
missed by 0.92. Should we lower toward ~0.85?

## Evidence (local `war_news_dev`, 14-day window)

### A. Confirmed same-event cluster (12 raw messages, Sep 7 maslakh)

| Metric | Value |
|--------|------:|
| Pair count | 66 |
| max(sim_ab, sim_ba) ≥ 0.92 | **1** |
| ≥ 0.87 | 2 |
| ≥ 0.85 | 3 |
| ≥ 0.80 | 4 |
| Average max pairwise sim | 0.58 |

Lowering to 0.85 would recover only ~2 additional pairs in this cluster.
Most same-event pairs sit in the 0.45–0.75 band because outlet framing /
URL / bilingual padding diverge — pre-dedup cannot catch them at any
threshold that remains safe.

### B. Proxy false-positive risk (same source, |Δt| < 1h, sim > 0.75)

| Bucket | Count |
|--------|------:|
| Different `condition_id`, sim ≥ 0.85 | **252** |
| Different `condition_id`, sim ≥ 0.87 | 240 |
| Different `condition_id`, sim ≥ 0.92 | 223 |
| Same condition, different village, sim ≥ 0.85 | 372 |

Different-condition pairs already clear 0.85/0.87 in large numbers (daily
summaries, shared bulletin templates, etc.). Lowering the pre-dedup
threshold would mark many **distinct events** as duplicates before
extraction.

## Recommendation

**Keep `0.92`. Do not lower without a labeled FP/TP study.**

Rationale:
1. Marginal TP gain on the motivating cluster (~2 pairs).
2. Large FP surface at 0.85–0.87 among different-condition messages.
3. The right place for same-event / different-`village_id` recovery is the
   Part 1c cross-village incident-level backstop (`≥0.87`, ≤30min,
   `possible_duplicate` only) — not pre-extraction raw_text dedup.

## Follow-up (optional)

If revisiting later: sample 50 pairs in the 0.85–0.92 band with human
labels (same event vs not), then re-estimate. Until that labeled set
exists, leave the shipped default unchanged.
