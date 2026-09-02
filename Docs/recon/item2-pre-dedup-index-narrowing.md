# Item 2 - Pre-extraction dedup narrowing regression

## Result: fixed

The regression was caused by the new, unindexed `raw_text %> :text` pg_trgm
predicate, not by `same_source`. The fix keeps source narrowing and removes `%>`.
The query already orders by `word_similarity()` and its caller rejects a top score
below the threshold, so the duplicate decision is unchanged without redundant
unindexed prefilter work.

The migration remains unapplied. Do not expect index-backed plans until it is run
manually:

```bash
docker compose exec backend alembic upgrade head
```

## Source distribution

Measured on 2026-09-02 on `war_news_dev`:

```text
 source_id | count
-----------+-------
        78 |    26
```

All 26 messages in the current 48-hour window came from source 78. Same-source
narrowing is not selective for messages from that source on this snapshot. Only
five messages were eligible after the status filter; candidate 2622 compared with
four. The opt-in `same_source_time_bucket` mode would not improve this sample:
the eligible messages span under two hours, while changing its default would also
exclude valid longer-lived same-source duplicates.

## EXPLAIN ANALYZE comparison

Each plan uses candidate `raw_messages.id = 2622`, the same snapshot, and
`EXPLAIN (ANALYZE, BUFFERS)`. The plans use an indexed one-row candidate subquery
instead of exposing the bound message text; this does not alter the candidate scan.

### Original: 4 candidates, 1.695 ms

```text
Limit  (cost=603.52..603.52 rows=1 width=12) (actual time=1.469..1.470 rows=1 loops=1)
  Buffers: shared hit=562
  ->  Sort  (cost=603.52..603.56 rows=18 width=12) (actual time=1.468..1.469 rows=1 loops=1)
        Sort Key: (word_similarity(rm.raw_text, raw_messages.raw_text)) DESC, rm.id
        Sort Method: top-N heapsort  Memory: 25kB
        Buffers: shared hit=562
        ->  Nested Loop  (cost=0.28..603.43 rows=18 width=12) (actual time=0.643..1.404 rows=4 loops=1)
              Join Filter: (rm.id <> raw_messages.id)
              Rows Removed by Join Filter: 1
              Buffers: shared hit=556
              ->  Index Scan using raw_messages_pkey on raw_messages  (cost=0.28..8.30 rows=1 width=198) (actual time=0.023..0.025 rows=1 loops=1)
                    Index Cond: (id = 2622)
                    Buffers: shared hit=6
              ->  Seq Scan on raw_messages rm  (cost=0.00..594.86 rows=18 width=198) (actual time=0.487..1.031 rows=5 loops=1)
                    Filter: ((raw_text IS NOT NULL) AND (status <> ALL ('{rejected,duplicate,materialized}'::message_status[])) AND (received_at >= (now() - '48:00:00'::interval)))
                    Rows Removed by Filter: 2106
                    Buffers: shared hit=550
Planning:
  Buffers: shared hit=305
Planning Time: 1.224 ms
Execution Time: 1.695 ms
```

### Regressed: 0 candidates, 2.457 ms

```text
Limit  (cost=603.48..603.49 rows=1 width=12) (actual time=2.113..2.115 rows=0 loops=1)
  Buffers: shared hit=562
  ->  Sort  (cost=603.48..603.49 rows=1 width=12) (actual time=2.111..2.112 rows=0 loops=1)
        Sort Key: (word_similarity(rm.raw_text, raw_messages.raw_text)) DESC, rm.id
        Sort Method: quicksort  Memory: 25kB
        Buffers: shared hit=562
        ->  Nested Loop  (cost=0.28..603.47 rows=1 width=12) (actual time=2.065..2.066 rows=0 loops=1)
              Join Filter: ((rm.id <> raw_messages.id) AND (rm.raw_text %> raw_messages.raw_text) AND (rm.source_id = raw_messages.source_id))
              Rows Removed by Join Filter: 5
              Buffers: shared hit=556
              ->  Index Scan using raw_messages_pkey on raw_messages  (cost=0.28..8.30 rows=1 width=206) (actual time=0.029..0.033 rows=1 loops=1)
                    Index Cond: (id = 2622)
                    Buffers: shared hit=6
              ->  Seq Scan on raw_messages rm  (cost=0.00..594.86 rows=18 width=206) (actual time=0.767..1.553 rows=5 loops=1)
                    Filter: ((raw_text IS NOT NULL) AND (status <> ALL ('{rejected,duplicate,materialized}'::message_status[])) AND (received_at >= (now() - '48:00:00'::interval)))
                    Rows Removed by Filter: 2106
                    Buffers: shared hit=550
Planning:
  Buffers: shared hit=403
Planning Time: 1.786 ms
Execution Time: 2.457 ms
```

### Fixed: 4 candidates, 1.443 ms

```text
Limit  (cost=603.64..603.64 rows=1 width=12) (actual time=1.279..1.280 rows=1 loops=1)
  Buffers: shared hit=562
  ->  Sort  (cost=603.64..603.68 rows=18 width=12) (actual time=1.278..1.278 rows=1 loops=1)
        Sort Key: (word_similarity(rm.raw_text, raw_messages.raw_text)) DESC, rm.id
        Sort Method: top-N heapsort  Memory: 25kB
        Buffers: shared hit=562
        ->  Nested Loop  (cost=0.28..603.55 rows=18 width=12) (actual time=0.572..1.251 rows=4 loops=1)
              Join Filter: ((rm.id <> raw_messages.id) AND (rm.source_id = raw_messages.source_id))
              Rows Removed by Join Filter: 1
              Buffers: shared hit=556
              ->  Index Scan using raw_messages_pkey on raw_messages  (cost=0.28..8.30 rows=1 width=204) (actual time=0.021..0.022 rows=1 loops=1)
                    Index Cond: (id = 2622)
                    Buffers: shared hit=6
              ->  Seq Scan on raw_messages rm  (cost=0.00..594.86 rows=23 width=204) (actual time=0.445..0.918 rows=5 loops=1)
                    Filter: ((raw_text IS NOT NULL) AND (status <> ALL ('{rejected,duplicate,materialized}'::message_status[])) AND (received_at >= (now() - '48:00:00'::interval)))
                    Rows Removed by Filter: 2106
                    Buffers: shared hit=550
Planning:
  Buffers: shared hit=315
Planning Time: 1.115 ms
Execution Time: 1.443 ms
```

The fixed query is 0.252 ms faster than original and 1.014 ms faster than the
regressed version. The migration was not run during this work.
