# Cursor-gap alert follow-up (Step 0)

## Finding

Live sweep cursor `live_sweep_new_only` was reporting `unhealthy: true`
(`last_processed_id=2531`, cursor `updated_at` ~2026-08-28, ID-space gap
799 vs `MAX(raw_messages.id)=3330`).

Queried all **641 actual rows** with `id > 2531`:

| Status | filter_result | Count |
|--------|---------------|------:|
| parsed | populated | 457 |
| rejected | populated | 61 |
| error | populated | 61 |
| routed_air_violation | populated | 44 |
| materialized | populated | 15 |
| duplicate | populated | 3 |

**0 rows** were `status='pending'` with `filter_result IS NULL`.

Sources: overwhelmingly **CNRS Webhook** (pre-classified, arrives `parsed`
with `filter_result` and `relevance_filtered_at` set at ingest) plus **Red
Alert Lebanon** (rejected / routed without live-sweep relevance).

## Conclusion

**Benign.** The alert fired because the health check compared
`MAX(raw_messages.id) - last_processed_id` and cursor staleness against *all*
new rows. The live-sweep cursor advances only when the relevance-filter stage
processes `pending` rows with no `filter_result`. CNRS-style pre-classified
traffic never touches that stage, so the cursor legitimately stops advancing
while the pipeline remains healthy.

## Recommendation implemented

Track **relevance-eligible backlog** instead of raw ID-space gap:

- `gap` = count of rows with `id > last_processed_id`, `status='pending'`,
  `filter_result IS NULL` (same criteria as the `relevance_filter` stage
  queue depth gauge).
- `unhealthy` when that backlog exceeds `pipeline_cursor_gap_row_threshold`,
  **or** the cursor is stale *and* such a backlog exists.

`max_raw_message_id` is retained in the API response for context but no
longer drives the unhealthy flag.

Per-source scoping was considered but rejected: the stage queue criteria
already encode “needs relevance filter” regardless of source, and a separate
per-source cursor would duplicate that signal without adding coverage.

Alternative considered: raise `pipeline_cursor_stale_minutes` — rejected
because it would silence real relevance stalls without fixing the metric.
