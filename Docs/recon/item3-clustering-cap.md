# Item 3 — Clustering service-level row cap

## Default proposed: `clustering_max_rows_per_pass = 100`

Matches the live sweep call-site cap (`STAGE_MAX_ROWS_PER_PASS = 100` in
`scripts/live_sweep_new_only.py`). Confirm or override via env
`CLUSTERING_MAX_ROWS_PER_PASS`.

## Change

- `ClusteringService.load_eligible_messages()` / `cluster_eligible()` enforce
  `min(caller max_rows, settings.clustering_max_rows_per_pass)`.
- Callers cannot exceed the service cap even when passing a larger `max_rows`.
- Remaining eligible rows wait for the next sweep pass (simple cap, no internal
  multi-batch splitting).

## Verification

Unit test `test_cluster_eligible_caps_rows_at_service_limit`: with service cap 5
and caller `max_rows=999`, SQL `LIMIT` is 5 and 5 rows are loaded from a 50-row
stub backlog.
