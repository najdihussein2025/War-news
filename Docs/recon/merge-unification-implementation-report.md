# Merge-unification implementation report (B1–B7 + Step 0)

Session date: 2026-09-03

---

## Step 0 — Cursor-gap alert (benign, fixed)

**Finding:** 641 rows with `id > sweep_cursors.last_processed_id` (2531); **0**
`pending` + `filter_result IS NULL`. All newer rows are pre-classified CNRS /
Red Alert traffic already past relevance filtering.

**Resolution:** `cursor_gap.gap` now counts relevance-eligible backlog only;
staleness fires only when that backlog is non-zero. Commits `ea277e6`, note
`Docs/recon/cursor-gap-followup.md` (`0c5e387`).

---

## Per-item summary

| Item | Commit | What changed |
|------|--------|--------------|
| **B1** | `a278a6b` | (pre-existing) Shared `IncidentMergeService.merge()` delegating to `merge_existing`. |
| **B2** | `0417cf9` | Fast-path confident-duplicate branch runs `find_best_match`; ≥0.80 merges via shared path; <0.80 writes `insufficient_score` audit + materializes with `duplicate_flag`; `_fast_path_worker` passes `DedupMatchingService`; `_insert_fast_incident(duplicate_flag=…)`; A1 tests updated. |
| **B3** | `ab51e94` | Fast-path window uses `dedup_time_window_days` (3d); removed `fast_dedup_time_window_minutes`. Embedding score ≥0.80 required before auto-merge (B2 guardrail). |
| **B4** | `fefcb1d` | Embedding targets `content_embedding IS NULL` regardless of status; stage moved after pre-extraction dedup / before Tier 1 (orchestrator + live sweep); Tier 2 inline embedding removed; health gauge aligned. |
| **B5** | `8b92c06` | Max-wins counts preserved; lower incoming values recorded as `{field}_suppressed` with `raw_message_id` + channel in `incident_updates.new_values`; full `detail.*` snapshots in audit. |
| **B6** | `03e0852` | `details_pending` reopened when merge adds a presence-category bool not already `True` on `incident_details`. |
| **B7** | (analysis) | See below — no code commit required. |

---

## Migration — pending user action

**File:** `alembic/migration/20260903_0048_add_insufficient_score_match_status.py`

Adds `insufficient_score` to PostgreSQL enum `match_status`.

**Not applied by agent.** Run:

```bash
alembic upgrade head
```

---

## B7 — Frontend / provenance audit

### `duplicate_matches.status` vs UI filters

Searched frontend + API list path:

- Incidents page `duplicate_only` filter maps to
  `Incident.duplicate_flag.is_(True)` (`incident_repository._list_filters`) —
  **not** `duplicate_matches.status`.
- No frontend reads `MatchStatus` or `duplicate_matches` for counts.

**Conclusion:** `insufficient_score` rows do **not** silently change existing
duplicate filter or dashboard numbers. They are audit-only until a dedicated
duplicates-review UI is built.

**Recommendation:** Exclude `insufficient_score` from any future "needs human
duplicate review" queue (which should stay `status='pending'`). Include them in
a general duplicates-audit / telemetry view alongside `confirmed_duplicate`.

### Merge reversibility / provenance

`merge_existing` now writes `incident_updates` with:

- Top-level casualty fields + `note` + `details_pending`
- Every `incident_details` column snapshotted as `detail.{column}`
- `{field}_suppressed` entries when incoming counts were lower than stored max

**Reversal UI:** Out of scope — reconstructing a merge from data alone is
possible; undo would need new UI/workflow (deferred follow-up).

---

## Design-decision compliance

All confirmed decisions implemented without silent deviation:

- Single shared merge path (B1/B2/B5/B6)
- Embedding score gate before fast-path merge (B2/B3)
- Unified 3-day dedup window (B3)
- Early embedding + no Tier 2 embed fallback (B4)
- Max-wins with provenance, not silent discard (B5)
- Selective `details_pending` reopen (B6)

---

## Observability interaction (B4)

- **Stage telemetry:** `pipeline_stage_runs` records stages by name as executed;
  reordering embedding earlier is reflected automatically — no hard-coded
  sequence assumed in telemetry code.
- **Health gauges:** `embedding` queue depth filter updated to match sweep
  selection (`content_embedding IS NULL` only), waiting-since anchored on
  earlier pipeline timestamps.

No conflict with A2–A6 observability work; reconciled in B4 commit.

---

## Tests

| Area | Result |
|------|--------|
| `tests/test_incident_merge_repository.py` | 3 passed (B5/B6) |
| `tests/test_incident_materialization_service.py` (incl. A1 fast-path updates) | passed |
| `tests/test_fast_path_dedup.py` | 4 passed |
| `tests/test_embedding_stage.py` | 1 passed |
| `tests/test_pipeline_health_service.py` | 12 passed |
| `tests/test_incident_merge_service.py` | 2 passed |
| **Key subset total** | **44 passed** |

### A1 test change (B2)

Replaced `test_fast_path_confident_duplicate_sets_fast_path_completed_at_only`
with:

- `test_fast_path_confident_duplicate_merges_when_score_high` — merge +
  `materialized_at` + `confirmed_duplicate` audit
- `test_fast_path_confident_duplicate_insufficient_score_materializes` —
  separate incident + `insufficient_score` audit + `duplicate_flag=True` (0.65
  score)

---

## Deferred

- Merge **reversal UI** (B7 flag)
- Dedicated admin view for `insufficient_score` audit rows (optional follow-up)
- Apply migration `20260903_0048` on live DB
