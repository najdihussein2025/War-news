# Item 2 — Pre-extraction dedup index and candidate narrowing

## Confirmed: no GIN trigram index on `raw_messages.raw_text`

Existing indexes on `raw_messages` (2026-09-02): pkey, source_platform,
source_name, duplicate_of_id, processing_claim_stage, content_embedding_hnsw,
unique (source_id, external_message_id). **No trigram index on `raw_text`.**

## Migration (generated, not applied)

`alembic/migration/20260902_0044_add_raw_messages_raw_text_trgm.py`

- `CREATE INDEX ix_raw_messages_raw_text_trgm ON raw_messages USING gin (raw_text gin_trgm_ops)`
- `CREATE INDEX ix_raw_messages_source_id_received_at ON raw_messages (source_id, received_at)`

**Run manually:** `docker compose exec backend alembic upgrade head`

## Query changes

- Default candidate narrowing: `pre_dedup_candidate_narrowing=same_source`
  (env `PRE_DEDUP_CANDIDATE_NARROWING`; also `none`, `same_source_time_bucket`).
- Optional time bucket: `pre_dedup_time_bucket_hours=6` when using
  `same_source_time_bucket`.
- 48-hour window now configurable: `pre_dedup_window_hours=48` (unchanged default).
- Added `%>` prefilter + `SET LOCAL pg_trgm.word_similarity_threshold` so the
  GIN index can be used once the migration is applied.

## EXPLAIN ANALYZE (dev DB, ~2,104 rows)

### Before (full 48h window, no source filter, no index)

```
Seq Scan on raw_messages
  Rows Removed by Filter: 2102
  Execution Time: 1.661 ms
```

### After code change, before migration (same_source + %> prefilter)

```
Seq Scan on raw_messages
  Filter: ... source_id = $1 AND raw_text %> $2 ...
  Rows Removed by Filter: 2104
  Execution Time: 105.023 ms
```

Seq scan remains until migration is applied; `%>` without GIN is expensive on
full table. After migration, expect `Bitmap Index Scan` on
`ix_raw_messages_raw_text_trgm` plus btree filter on
`ix_raw_messages_source_id_received_at`.

At current dev volume only 2 rows fall in the 48h window; the 20k labeled corpus
is not wired to this DB — re-run EXPLAIN after migration on production-scale data.
