# Pipeline Observability — Implementation Report

Scope: pipeline observability items 1–6 (Phase A). Human-visible data only —
no automated alerting, no SLO pass/fail gate.

---

## 1. What was built, per item

### Item 1 — `pipeline_stage_runs` table + orchestrator telemetry
**Commit `bd51b6d`** — *Persist pipeline stage run telemetry*

- New `pipeline_stage_runs` table (migration `20260902_0045`).
- `run_full_pipeline_sweep` records one row per stage per sweep pass
  (`sweep_type` = `manual` | `live`) via `record_stage_run`. Telemetry
  failures are swallowed so a completed processing stage can never be
  turned into a failure.

### Item 2 — per-row pipeline stage timestamps
**Commit `086b577`** — *feat(observability): finish per-row pipeline stage timestamps (item 2)*

- Migration `20260902_0046` adds 8 nullable, individually indexed
  `timestamptz` columns to `raw_messages`:
  `relevance_filtered_at`, `dedup_checked_at`, `extracted_at`,
  `matched_at`, `fast_path_completed_at`, `tier2_completed_at`,
  `embedded_at`, `materialized_at`.
- Wiring:
  - `relevance_filtered_at` / `extracted_at` / `matched_at` /
    `embedded_at` — set in `RawMessageRepository` alongside the
    corresponding result write.
  - `dedup_checked_at` — set in `process_pre_dedup_message`, committed in
    every branch (duplicate and non-duplicate).
  - `fast_path_completed_at` — set in the same commit as fast path's own
    materialization branch (`_mark_materialized(fast_path=True)`) and its
    duplicate-link branch. Stays `NULL` for rows that go through full
    materialization or terminalize.
  - `tier2_completed_at` — set in the same commit that flips
    `details_pending` → `false`, only when ≥ 1 pending incident actually
    needed filling.
  - `materialized_at` — set from **both** paths that produce a
    materialized incident: fast path's own branch, and the full
    materialization stage (including merge-into-existing). No materialized
    row is left with it unset; a fast-path row is never re-stamped by the
    full stage.
- Focused tests, including the "remains NULL when this path wasn't taken"
  cases. Two transposed `pre_extraction_dedup` commit-count assertions
  fixed.

### Item A2 — per-stage queue depth + oldest-waiting age
**Commit `2ad34a7`** — *feat(observability): per-stage queue depth + oldest-waiting age (item A2)*

- `PipelineHealthService.stage_queue_depths()` — one read-only aggregate
  query per stage: rows currently eligible and waiting + age of the
  oldest. Each stage's filter mirrors its claim query in
  `PipelineClaimRepository` (and the plain-select post stages in
  `pipeline_sweep_stages`): `relevance_filter`, `pre_extraction_dedup`,
  `tier1_extraction`, `matching`, `fast_path`, `tier2_detail_fill`,
  `embedding`, `materialization`.
- "Waiting since" uses the item-2 timestamps: `matching` waits since
  `extracted_at`, `fast_path` since `matched_at`, etc. (COALESCE back to
  `received_at` for rows that predate the columns). `tier2_detail_fill` is
  an incident-level queue → `Incident.created_at`.
- The claim lease predicate was extracted into
  `claimable_lease_filter()` so the health check and the claim repository
  share one definition. `tier1_extraction` / `matching` include it (their
  claim queries do); `fast_path` does not (its claim query does not).
- **Clustering is intentionally excluded** — it has no row-level claim
  query to mirror (in-memory clustering pass over all match-eligible rows).
- Exposed as `GET /api/pipeline/health`, guarded by `require_super_admin`
  (identical to `POST /api/pipeline/sweep`).

### Item A3 — live-sweep cursor gap
**Commit `34e2645`** — *feat(observability): live-sweep cursor gap check in /api/pipeline/health (A3)*

- `PipelineHealthService.cursor_gap()` compares
  `sweep_cursors.last_processed_id` for `live_sweep_new_only` against
  `MAX(raw_messages.id)`.
- Folded into `GET /api/pipeline/health`; the response is now an object:
  `{ stages: [...], cursor_gap: {...}, latency: {...} }`.
- `cursor_gap = { sweep_name, last_processed_id, max_raw_message_id, gap,
  unhealthy }`. `unhealthy` is a **data field, never a status code** — the
  endpoint returns HTTP 200 regardless.
- `LIVE_SWEEP_NAME` centralised in `app/news/models/sweep_cursor.py`;
  `scripts/live_sweep_new_only.py` imports it.

### Item A4 — latency percentile reporting
**Commit `40fda1c`** — *feat(observability): latency percentile summary in /api/pipeline/health (A4)*

- `PipelineHealthService.latency_summary()` — p50/p95/p99 of
  `received_at → "done"` over a rolling 24h window, added as a `latency`
  block: `{ window_hours, materialized: {...}, terminal_non_materialized:
  {...} }`, each `{ p50_seconds, p95_seconds, p99_seconds, sample_size }`.
  **No pass/fail SLO target field.**
- **Design decision — materialized vs `routed_air_violation` / terminal
  `error`: kept SEPARATE, in two cohorts.**
  - `materialized` = `received_at → materialized_at`. The happy-path
    end-to-end latency an SLO would eventually target, and the only cohort
    with a dedicated item-2 "done" timestamp.
  - `terminal_non_materialized` = `received_at → matched_at` for rows that
    ended in `routed_air_violation` or terminal `error`. Folding these
    into the happy path would bias it: air-violation rows exit early at
    routing (short), error rows exit after a retry long-tail (long), and
    item 2 added no `routed_at` / `errored_at` column, so `matched_at` is
    the terminal reference. Exposed alongside, not merged.

### Item A5 — admin health view
**Commit `f14a59d`** — *feat(observability): admin pipeline health view (A5)*

- Read-only **"Pipeline"** tab added to the existing Logs page
  (`frontend/src/features/logs`) — no new folder, no new route. Shown only
  under `/superadmin/logs` (the endpoint is super-admin only).
- `PipelineHealthPanel` renders the full `/api/pipeline/health` response,
  styled to match the other Logs tables:
  - per-stage queue table (`DataTable`): stage, queue depth, oldest
    waiting (humanised);
  - cursor-gap block — the whole block switches to the danger surface
    (`border-danger bg-danger/5`) with a red **"Unhealthy"** badge and red
    gap number when `cursor_gap.unhealthy` is true;
  - latency percentiles — two cohorts with p50/p95/p99 + sample size,
    labelled "no SLO target".
- **Manual "Refresh" button only.** `usePipelineHealthQuery` sets
  `refetchInterval: false`, `refetchOnWindowFocus: false`,
  `staleTime: Infinity`. No auto-refresh / polling anywhere in Phase A.

---

## 2. Migrations generated across the whole observability effort

| Order | Revision | Purpose | Item | State |
|------:|----------|---------|------|-------|
| 1 | `20260902_0045_add_pipeline_stage_runs` | `pipeline_stage_runs` telemetry table | 1 | **Applied** |
| 2 | `20260902_0046_add_raw_message_stage_timestamps` | 8 per-row stage `timestamptz` columns + per-column indexes on `raw_messages` | 2 | **Applied** |

A2–A5 generated **no** schema migrations. A3's two thresholds are
`Settings` fields with env overrides, not columns.

`alembic current` / `alembic heads` both report **`20260902_0047 (head)`**
— the DB is fully up to date. `20260902_0047_add_incidents_list_indexes`
belongs to the separate incidents-page read-path track, not this effort,
and is already applied.

**Nothing pending from the observability effort.**

---

## 3. Real end-to-end latency number (A1 verification query)

Query: `materialized_at - received_at`, run against `war_news_dev`.

- **Fixture row** (synthetic, single row, transaction rolled back — no
  persistence):

  | sample_size | p50 | p95 | p99 | min | max |
  |---|---|---|---|---|---|
  | 1 | `00:01:11` | `00:01:11` | `00:01:11` | `00:01:11` | `00:01:11` |

  `EXPLAIN`: `Bitmap Index Scan on ix_raw_messages_materialized_at` — the
  new item-2 index is used, no seq scan.

- **Fixture distribution** (20 synthetic materialized rows, latency
  30–600 s, rolled back): p50 **315.0 s**, p95 **571.5 s**, p99
  **594.3 s** (sample_size 20). Terminal cohort (6 rows): p50 35.0 s, p95
  57.5 s, p99 59.5 s.

- **Live production data:** 0 rows currently carry `materialized_at` — the
  live `parsed` / `pending` queue is empty and nothing has been
  re-materialized since migration `20260902_0046` was applied. 64 rows
  carry `tier2_completed_at`; `tier2_completed_at - received_at` p50
  ≈ **5 d 4 h** — a backlog artifact (week-old messages whose detail-fill
  backlog only just drained), not steady-state latency.

The real end-to-end number will only become meaningful once fresh traffic
flows through to `materialized_at` again.

---

## 4. A3 thresholds (stated plainly)

| Setting (env var) | Default | Meaning |
|---|---|---|
| `pipeline_cursor_gap_row_threshold` (`PIPELINE_CURSOR_GAP_ROW_THRESHOLD`) | **500** | `unhealthy` when `MAX(raw_messages.id) - last_processed_id` exceeds this. |
| `pipeline_cursor_stale_minutes` (`PIPELINE_CURSOR_STALE_MINUTES`) | **30** | `unhealthy` when the cursor has not advanced in this many minutes **and** newer rows exist (`sweep_cursors.updated_at` is written only when the cursor advances). |

`unhealthy = (gap > row threshold) OR (stalled that long with newer rows)`.

**Live observation at implementation time:** the real cursor reports
`last_processed_id = 2531`, `MAX(id) = 2709`, `gap = 178`,
`unhealthy = true` — the cursor's `updated_at` is ~5 days old while 178
newer rows exist. See §7.

Latency window: `LATENCY_WINDOW_HOURS = 24` (module constant, not a
setting).

---

## 5. Test results

| Suite | Result |
|---|---|
| Observability-scoped backend tests (materialization, tier2, fast-path, pre-dedup, `pipeline_health_service`, `pipeline_health_route`, claim, orchestrator, sweep CLI guard, fast-path concurrent dedup, dedup matching) | **67 passed, 0 failed** |
| Frontend suite (`vitest run`) | **36 passed, 0 failed** (9 files) — includes `PipelineHealthPanel.test.tsx` (SSR render of healthy + unhealthy) and the `apiContracts` entry for `GET /pipeline/health` |
| Frontend `tsc --noEmit` / `vite build` | clean |

**Full backend suite:** 322 passed, **12 failed**. All 12 failures are
pre-existing and unrelated to observability — they live in
`test_cnrs_webhook.py` (new `skipped_before_cutoff` response field from
concurrent CNRS work), `test_seed_villages.py`
(`unhashable type: SimpleNamespace` in `seed_villages.py`),
`test_matching_service.py` (village-match behaviour change),
`test_red_alert_collector.py` / `test_incident_detail.py`
(`incidents_created_by_fkey` FK violation — test-DB seeding). None touch
`pipeline_health`, the `raw_messages` timestamp columns, `pipeline_claim`,
or any file changed in Phase A.

---

## 6. Explicitly deferred scope

- **No SLO pass/fail target.** The `latency` block reports raw percentiles,
  `sample_size` and `window_hours` only. No target value, no met/not-met
  field, anywhere in the API or the UI.
- **No automated alerting.** `cursor_gap.unhealthy` is a data field
  surfaced in the API and rendered distinctly in the admin view. Nothing
  pages, emails, posts to Slack, or changes an HTTP status code off it.
- **No auto-refresh / polling.** The admin view refreshes only on an
  explicit button press.
- **Clustering** has no queue-depth gauge (no row-claim query to mirror).
- **Terminal-cohort latency** uses `matched_at` as a proxy "done"
  timestamp because item 2 added no `routed_at` / `errored_at` column.

---

## 7. What to watch next

Once enough real traffic has flowed to populate `materialized_at` again
(the live queue is currently drained), revisit the `latency.materialized`
p95 over a week or two of steady state and use it to decide a **defensible
SLO target** — which is deliberately not set now, because a target chosen
against zero real samples would be arbitrary.

Separately, the live-sweep cursor is **currently stale** (`updated_at`
~5 days old, 178 newer rows, `unhealthy = true`). This is worth a look:
rows ingested pre-classified (e.g. via the CNRS webhook) are never
"processed" by the relevance sweep, so they never advance
`sweep_cursors.updated_at`, which can leave the staleness check firing
even when the pipeline is healthy. If that turns out to be the common
case, `pipeline_cursor_stale_minutes` should be raised, or the staleness
check should compare against the newest *relevance-eligible* row rather
than `MAX(raw_messages.id)`.
