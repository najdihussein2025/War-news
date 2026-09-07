# Spec vs implementation — flow-by-flow review

**Date:** 2026-09-04  
**Purpose:** Compare the written Flow & Database spec against the actual codebase. Analysis only — no code was changed in this pass.  
**Scope:** Flows A–J as sectioned in the spec (auth, ingestion, pipeline stages, duplicates, incidents, air violations, import/export, sources, logs, operations).

---

## A. Authentication & session flow

**Implementation found:** `app/api/auth_router.py` (`POST /api/auth/login`, `/logout`, `GET /api/auth/me`); `app/accounts/services/auth_service.py`; `app/api/deps.py` (`get_current_user`, `require_admin`, `require_super_admin`); models in `app/accounts/models/` and `app/logs/models/login_log.py`; frontend `frontend/src/features/auth/*`, `stores/authStore.ts`, `app/routes.tsx`. Accounts are created only via Super Admin (`POST /api/accounts`) plus startup seed / empty-DB bootstrap.

**How it actually works:**

- Login checks IP throttle (`login_throttles` key `ip:{host}`), then a **device** throttle (`device:{sha256(login_device_id)}`), then `users.locked_until`, then bcrypt against `password_hash`.
- Success creates `auth_sessions` with SHA-256 `token_hash`, 8-hour `expires_at`, resets failure counters, sets `last_login_at`. The raw token is put in an HttpOnly `access_token` cookie (12-hour `max_age`) and is **not** returned in JSON.
- Failure increments IP + device throttles and, if the user exists, `failed_login_attempts` / `locked_until` (3 failures / 5 minutes).
- Every attempt writes `login_logs`. Logout sets `revoked_at`. Authenticated requests resolve cookie first, then `Authorization: Bearer`.

**Spec vs. reality differences:**

- Token is cookie-only, not a bearer returned in the body (frontend never sends `Authorization`).
- Extra device-level throttle and `login_device_id` cookie (hardcoded `secure=False`).
- `user_id` is written on successful login only — not on invalid / inactive / rate-limited attempts, even when the user is known.
- Inactive accounts are rejected **after** password verify.
- Extra: `POST /api/accounts/bootstrap` (unauthenticated if zero users); optimistic locking / edit-lock columns on `users`.
- Orphaned duplicate field declarations sit **outside** the `User` class at the bottom of `app/accounts/models/user.py` (lines 97–107).

**Risk/quality notes:**

- Session TTL (8h) and cookie TTL (12h) disagree — leftover cookie can 401-loop after the session dies.
- Lockout does not revoke existing sessions.
- Throttle increments are read-modify-commit, not atomic.
- Client IP is `request.client.host` only (wrong behind a proxy).
- Default seed password is `"password"` in config.

**Ideas to discuss:**

1. Align cookie max-age with `expires_at`, and decide whether lockout should revoke live sessions.
2. Write `user_id` on failed logins when the username matched a real account, so lockout investigations are usable.
3. Fix or delete the orphaned tail of `user.py` before it is mistaken for schema.
4. Confirm whether cookie+SameSite is the intended auth model (spec still describes a returned bearer).

---

## B. Ingestion flow

**Implementation found:**

- CNRS webhook: `POST /webhooks/cnrs-posts` → `app/sources/actions/receive_cnrs_webhook_action.py`
- CNRS poll: `scripts/cnrs_poll_worker.py` (Docker loop every 300s) **and** `app/core/scheduler.py` `_poll_cnrs` **and** shared `IngestSourceAction`
- Red Alert: `app/sources/services/red_alert_collector.py` + `app/core/scripts/run_red_alert_collector.py`
- Air-violation webhook: `POST /webhooks/air-violations` → `AirViolationService.create`
- Workbook import: `POST /api/incidents/import`, `POST /api/air-violations/import` (Super Admin)
- Manual CRUD: `POST /api/incidents`, `POST /api/air-violations` (Admin+)

**How it actually works:** CNRS webhook/poll insert `raw_messages` with `status=pending`, unique `(source_id, external_message_id)`, and honor `content_source_blocks`. Only the **webhook** enqueues a pipeline sweep. Red Alert writes `raw_messages` for air-keyword posts and immediately routes them into `air_violations` (`status=routed_air_violation`). The air-violation webhook, workbook imports, and manual CRUD write `incidents` / `air_violations` **directly** with `raw_message_id=NULL`. Secrets live in env vars; `sources.auth_secret_ref` stores a name.

**Spec vs. reality differences:**

- Spec: “all paths land in `raw_messages` except the air-violation webhook.” Reality: manual incident/air CRUD and both workbook imports also bypass `raw_messages`.
- Three CNRS poll implementations, not one; Docker poll hardcodes `SOURCE_ID = 3` and does not enqueue a sweep or set `source_platform_id`.
- CNRS `include=false` posts are counted `flagged` but **still inserted** as `pending` and enter the pipeline.
- Red Alert silently drops non-air Telegram posts (never persisted). Condition 45 is used as “unclassified air.”
- Extra table: `pipeline_sweep_jobs` (created at runtime in `pipeline_jobs.py`, not Alembic). Extra Docker worker: `backlog-relevance-worker`. Redis exists (caching), not in the spec’s architecture sketch.

**Risk/quality notes:**

- Poll vs webhook cursor schemes differ (numeric CNRS id vs `sources.last_cursor` vs prefixed `twitter:…` ids) — easy to miss or double-fetch.
- Blocking requires both `source_platform` and `origin_account`; missing either bypasses the block.
- `external_message_id` is nullable; Postgres unique constraints allow multiple NULLs.
- Red Alert ingestion logs only when new air-violation rows are created — duplicate-only cycles are invisible.
- `write_ingestion_log` rolls back the session first.

**Ideas to discuss:**

1. Collapse CNRS poll to one worker and always enqueue a sweep after new rows, matching the webhook path.
2. Decide whether CNRS `include=false` should be stored, rejected, or parked for review.
3. Persist (or log) Red Alert discards so there is an audit trail for filtered Telegram posts.
4. Confirm that workbook/manual rows with no `raw_message_id` is intentional — they skip every pipeline duplicate layer.

---

## C. Core pipeline flow

**Implementation found:** Orchestrator `app/news/services/pipeline_orchestrator.py` (`run_full_pipeline_sweep`); concurrent workers in `pipeline_concurrent_sweeps.py` / `pipeline_llm_workers.py`; claims in `pipeline_claim_repository.py`; advisory lock `pipeline_advisory_lock.py` (key `84729103`); worker `app/core/scripts/run_pipeline_worker.py`; live sweep `scripts/live_sweep_new_only.py`; admin trigger `POST /api/pipeline/sweep`.

**Actual stage order:** relevance → pre-extraction dedup → **embedding** → tier1 → matching → fast_path → tier2 → clustering → materialization (reconciliation inlined at the end). Spec order puts embedding after tier2.

Webhook sweeps: `use_advisory_lock=False` + `FOR UPDATE SKIP LOCKED`. Manual/CLI: advisory lock for the whole sweep. Per-item failures continue; Ollama 401 aborts the current LLM stage and stops later LLM stages.

### C1. Relevance filter

**Implementation found:** `pipeline_sweep_stages.sweep_relevance_filter` → `FilterRelevanceAction` (`app/llm/actions/filter_relevance_action.py`) → `relevance_filter_service.policy_for_result`.

**How it actually works:** Claims `pending` + `filter_result IS NULL` with SKIP LOCKED. Trusted sources skip LLM; CNRS classification can skip LLM; keyword prefilter auto-rejects if no village/action keywords; remaining go to Ollama in batches of 15. Writes `filter_result`, `low_confidence_relevance`, `relevance_filtered_at`.

**Spec vs. reality differences:** Uncertain verdict is stored as **`rejected`** with `needs_review=True`, not allowed to proceed. Relevant → `parsed`. Irrelevant / keyword-miss → `rejected`. Extra gates: trusted-source bypass, CNRS pre-class, keyword prefilter. Reviewer classifier is wired but idle.

**Risk/quality notes:** The claimed batch stays locked while the LLM runs (spec: do not hold a DB session across Ollama). Uncertain items only surface later on Rejected News, not in the extraction path.

**Ideas to discuss:**

1. Spec vs product: should uncertain proceed, stay rejected-for-review, or become a first-class `needs_review` status?
2. Close the session before the Ollama call, matching the tier1/tier2 worker pattern.

### C2. Pre-extraction dedup

**Implementation found:** `pipeline_concurrent_sweeps.sweep_pre_dedup_concurrent` → `pre_extraction_dedup.py`; GIN trigram index on `raw_text`.

**How it actually works:** Eligible `parsed` rows with no extraction. `word_similarity` over last 48h (`pre_dedup_window_hours`), threshold 0.92. Lower ID wins; higher gets `status=duplicate` + `duplicate_of_id`. Always sets `dedup_checked_at`. Optional same-source narrowing.

**Spec vs. reality differences:** Matches the idea. Extra: window, narrowing modes, timestamp. Does **not** write `duplicate_matches`.

**Risk/quality notes:** 0.92 is strict; same-source narrowing misses cross-channel copies. Window is `received_at`, not event time.

**Ideas to discuss:**

1. Whether this layer should also emit a `duplicate_matches` row for later human review.
2. Whether cross-source near-duplicates should be in scope.

### C3. Tier-1 extraction

**Implementation found:** `sweep_extraction_concurrent` → `run_tier1_extraction_for_message` → `OllamaExtractionService.extract_tier1`. Legacy sync `sweep_extraction` is **not** used by the orchestrator.

**How it actually works:** Claims `parsed` with no `extraction_result`. LLM produces core event/casualty + presence categories into `extraction_result`. Concurrent path: load text, **close session**, call Ollama, reopen to save. Retries via `extraction_retry_count`; cap → `error`.

**Spec vs. reality differences:** Presence gate is inside tier1, not a separate stage. Success leaves status `parsed` (not a new status). Combined presence+extraction mode is configurable.

**Risk/quality notes:** Legacy sync path still holds the session during LLM if anyone calls it. Default concurrent cap is 2 (`tier1_llm_max_concurrent_requests`).

**Ideas to discuss:**

1. Delete or quarantine unused sync sweeps so they cannot be wired back in.
2. Align telemetry stage names (`extraction` vs `tier1_extraction`).

### C4. Matching

**Implementation found:** `MatchIncidentAction` + `MatchingService`; village/condition trigram in `VillageRepository.find_similar` / `ConditionRepository.find_similar`; `AirViolationRepository.route_from_match`.

**How it actually works:** Resolves each extracted village mention plus condition text. Multi-village supported. Thresholds ~0.6 matched / ~0.35 low-confidence. Writes `match_result`. If condition ∈ {35, 36, 38, 45}, **creates/updates `air_violations` immediately**; raw_message stays `parsed` until fast_path terminalizes it.

**Spec vs. reality differences:** Spec places air routing in fast_path. Code splits: row created at matching, `status=routed_air_violation` set later.

**Risk/quality notes:** Transient match failures retry via `match_retry_count`. Low-confidence village matches still flow into later stages.

**Ideas to discuss:**

1. Document (or unify) “create AV at match, terminalize at fast_path” so ops don’t think routing failed when status is still `parsed`.
2. Whether low-confidence matches should materialize, flag, or stop.

### C5. Fast path

**Implementation found:** `sweep_fast_path_concurrent` → `IncidentMaterializationService.process_fast_path`; `fast_path_dedup.py`; `fast_path_eligibility.py`; per-pair `pg_advisory_xact_lock(village_id, condition_id)`.

**How it actually works:** For each materializable village: window-dedup (same village+condition, default **3 days**); else insert a minimal `incidents` row with `details_pending=true` and a thin `incident_details`. Sets raw_message **`status=materialized`**. All villages confident-dup → `duplicate`. Air conditions → `routed_air_violation`.

**Spec vs. reality differences:** Extra terminal status `materialized` (not in spec enum). Window is days, not a short bulletin window. Embedding score can auto-merge (≥0.80) or flag (≥0.50) on top of the village+condition hit.

**Risk/quality notes:** 3-day window can collapse distinct events. Fast-path `duplicate_matches` with `matched_incident_id=NULL` never appear in the review UI. Exact-hash collisions skip the village rather than linking to the existing row.

**Ideas to discuss:**

1. Revisit the 3-day window vs a tighter bulletin window.
2. Add `materialized` to the spec/enums so docs match production.
3. Surface raw-message-only duplicate links somewhere reviewers can see.

### C6. Tier-2 detail fill

**Implementation found:** `sweep_tier2_detail_fill_concurrent` → `tier2_detail_fill_service.py`; LLM in `pipeline_llm_workers` (session closed during Ollama).

**How it actually works:** Claims incidents with `details_pending=true`. Second LLM pass fills category fields, recomputes death/injury rollups, copies `content_embedding` onto `incidents.khabar_embedding`, clears `details_pending`. Optional semantic-dedup backstop.

**Spec vs. reality differences:** Matches intent. Embedding of khabar is copied here, not generated in the embedding stage.

**Risk/quality notes:** If fast_path skipped an incident as a duplicate, tier2 never runs and `khabar_embedding` may stay null.

**Ideas to discuss:**

1. Whether skipped duplicates should still get embeddings for later semantic review.
2. Gate-field / DID normalization on LLM-filled details, not only on human PATCH.

### C7. Embedding

**Implementation found:** `sweep_embedding_generation` → `EmbeddingService` (`paraphrase-multilingual-MiniLM-L12-v2`, 384-dim).

**How it actually works:** Any row with `content_embedding IS NULL` (no status filter). Local sentence-transformers encode, not Ollama. Sequential, not concurrent. Writes `content_embedding` + `embedded_at`.

**Spec vs. reality differences:** Runs **before** tier1 in the orchestrator, not after matching. Does not write `incidents.khabar_embedding`.

**Risk/quality notes:** DB session is held during CPU encode. Unfiltered status means rejected/error rows can be embedded too.

**Ideas to discuss:**

1. Keep early embedding (helps fast-path semantic gate) but update the spec so the order is official.
2. Skip embedding for already-rejected rows to save CPU.

### C8. Clustering

**Implementation found:** `sweep_clustering` → `ClusteringService` + `ChannelTrustTierRepository`; side effects in `pipeline_sweep_stages.py`.

**How it actually works:** In-memory clusters of `parsed` messages with embedding + match, same village, time window (~300 min), cosine ≥ 0.75. Picks representative by trust tier (`official` > `trusted` > `detail`), then time, then id. Materializes the representative. Subsumed members: raw_message `duplicate` + `duplicate_of_id`.

**Spec vs. reality differences:** Spec says soft-delete subsumed **incidents**. Code comment and `soft_delete_for_raw_message_id` **preserve** incidents and only write `duplicate_matches` / redirect pending links. Function name is misleading.

**Risk/quality notes:** One transaction per cluster; cluster failure rolls the whole cluster. Not in pipeline-health queue-depth list (in-memory pass).

**Ideas to discuss:**

1. Rename `soft_delete_for_raw_message_id` to match “preserve + link” behavior, and update the spec.
2. Decide whether subsumed incidents should stay visible, be flagged, or actually soft-delete.

### C9. Materialization

**Implementation found:** `sweep_materialization` → `IncidentMaterializationService.materialize`.

**How it actually works:** Remaining `parsed` + matched rows: one incident per eligible village, full details, `details_pending=false`, merge if embedding similarity is high. Sets `status=materialized`. Most live traffic already went through fast_path; this is backlog / clustering representatives.

**Spec vs. reality differences:** Dual materialization (fast_path then full) is real; spec reads as one insert point. Extra `materialized` status.

**Risk/quality notes:** Sweep query does not exclude rows that already have an active incident — relies on inner logic. Exact-hash unique index is the last safety net.

**Ideas to discuss:**

1. Whether fast_path + later full materialize is still the desired split, or whether one path should own inserts.
2. Make exact-hash conflicts return the existing row instead of silently skipping.

### C10. Duplicate-match reconciliation

**Implementation found:** `duplicate_match_reconciliation.reconcile_orphaned_soft_deleted_incidents`, called at the **end of `sweep_materialization`**, not as its own orchestrator stage.

**How it actually works:** Backfills `duplicate_matches` for `is_deleted=true` incidents that have none; redirects pending matches whose canonical was deleted.

**Spec vs. reality differences:** Not a standalone stage. It targets soft-deleted orphans, but clustering no longer soft-deletes — so much of this pass may be a no-op on current data.

**Risk/quality notes:** Does not unify pre-dedup / fast-path / semantic evidence into one review record.

**Ideas to discuss:**

1. Either restore clustering soft-deletes, or rewrite reconciliation to cover the links clustering actually writes.
2. Build one review queue over all `duplicate_matches` shapes, not only incident-to-incident `pending`.

---

## D. Duplicate strategy

**Implementation found:** Unique constraint on `raw_messages`; `pre_extraction_dedup.py`; `fast_path_dedup.py` + 3-day window; partial unique index `uq_incidents_exact_hash_active`; `dedup_matching_service.py` (weights action 0.35 / embed 0.45 / time 0.20; high 0.80 merge, low 0.50 flag); `duplicate_match.py`; human API `GET/POST /api/incidents/{id}/duplicate-candidate|resolution`; UI on `IncidentDetailPage.tsx` only.

**How it actually works:** Layers exist and are wired. Human review is after-the-fact on incidents with `duplicate_flag` and a **pending incident-to-incident** match. Auto-merge writes `incident_updates.action=pipeline_merge` with `performed_by=NULL`. Confirm-duplicate soft-deletes the loser.

**Spec vs. reality differences:**

- `MatchStatus.insufficient_score` exists in DB/enum and is **never written** — sub-threshold cases use `pending` + `duplicate_flag` (log line says “insufficient_score”).
- Pre-extraction and clustering duplicates stay on `raw_messages` only.
- Fast-path can write `duplicate_matches` with `matched_incident_id=NULL` (invisible to the review endpoint, which requires a matched incident).
- `DuplicateBadge` component is unused. No duplicates queue page.

**Risk/quality notes:** Review UI covers one layer. Text normalization differs across layers (emoji-stripped `exact_hash` vs raw trigram/clustering). Broad 3-day window plus high auto-merge threshold can both over-collapse and under-review.

**Ideas to discuss:**

1. One duplicates inbox listing all pending (and raw-message-only) matches.
2. Either start writing `insufficient_score` or drop it from the enum/spec.
3. Unify text normalization so the same bulletin cannot dodge one layer and hit another.
4. Confirm the 3-day window is a product decision, not leftover config.

---

## E. Incident management flow

**Implementation found:** `app/api/incidents_router.py`; `incident_service.py` / `incident_repository.py`; detail edit `incident_detail_edit_service.py`, `incident_detail_field_registry.py`, serializer; frontend `IncidentsPage.tsx`, `IncidentDetailPage.tsx`, `incidentCategorySections.ts`, `incidentEditHelpers.ts`. Extra: verification endpoint, 5-minute edit locks, optimistic `version`.

**How it actually works:** Admin+ can list/create/update/delete. List filters: village, condition, source type, date range, `duplicate_only`, `flagged_only`, `verification_status`. Category PATCH enforces gates (flag 0 blanks subfields) and DID ∈ {D, ID, null}. Soft delete sets `is_deleted`. Detail edits and verification write `incident_updates`; pipeline merges write `pipeline_merge`.

**Spec vs. reality differences:**

- Header PUT (khabar, dates, links) does **not** write `incident_updates`.
- Delete does **not** write `UpdateAction.delete` (enum exists, unused). `create` and `undo` are also unused.
- `verification_status=needs_verification` on the list API is driven partly by raw-message match-confidence JSON, not only the incident column.
- Extra UI: Rejected News (`/api/rejected-news`, restore to reprocess). Map API exists (`GET /api/map/events`) but routes redirect `/map` to the dashboard.
- Spec: every change including delete/undo is auditable — not true for header edits, create, or delete.

**Risk/quality notes:** Gate/DID rules apply on PATCH, not on pipeline fill or workbook import. Edit lock is required for delete/duplicate resolve. No API to read `incident_updates`.

**Ideas to discuss:**

1. Write `incident_updates` for create, header edit, and delete, and expose a history panel on the detail page.
2. Apply the same gate/DID sanitizer on pipeline and import writes.
3. Clarify verification filter semantics so the UI chips match the SQL.
4. Either ship the map or remove the dead route/API to avoid confusion.

---

## F. Air violations flow

**Implementation found:** Model `app/news/models/air_violation.py`; CRUD `app/api/news_router.py` prefix `/api/air-violations`; webhook in `webhooks_router.py`; pipeline IDs in `fast_path_eligibility.py`; Red Alert `red_alert_air_violation_service.py`; frontend `AirViolationsPage.tsx`.

**How it actually works:** Separate table, no `incident_details`. Webhook creates rows with a shared secret (`AIR_VIOLATION_WEBHOOK_ENABLED` + `AIR_VIOLATION_WEBHOOK_SECRET`). Pipeline conditions 35/36/38/45 skip incident materialization. Admin+ CRUD with edit locks. Import Super Admin; export Admin+ (because `require_admin` includes both roles).

**Spec vs. reality differences:**

- CRUD/import allow only **{35, 36, 38}**; pipeline/Red Alert also use **45** (unclassified air). Cleanup script only looks at 35/36/38.
- Pipeline creates the AV row at matching time (see C4), not only at fast_path.
- Red Alert is a major writer the spec treats as “ingestion of raw messages,” not as a direct AV factory.

**Risk/quality notes:** Condition 45 can exist from the pipeline but cannot be created/edited/imported via admin tools. No `incident_updates`-style history table for air violations.

**Ideas to discuss:**

1. Treat 45 as a first-class condition in CRUD/import/export, or stop routing to it.
2. Add a light change log for air-violation edits (parity with incidents).
3. Confirm webhook vs Red Alert vs pipeline should all land in the same table with the same required fields.

---

## G. Import / export flow

**Implementation found:** Incident import `incident_workbook_service.py` + `POST /api/incidents/import`; air import/export `air_violation_workbook_service.py`; Settings UI `SettingsPage.tsx` (Super Admin import panels); air export button on `AirViolationsPage`. View `incident_excel_view` (migration `20260903_0050`) — **no HTTP incident export**.

**How it actually works:** Incident import maps ~186 workbook headers, resolves village/condition/source from DB (`LOOKUP_ONLY_HEADERS`), inserts `Incident` + `IncidentDetail` with no `raw_message_id` and **no duplicate checks**. Air import is 11 columns into `air_violations`. Air export streams `air_violations.xlsx`. Extra columns `source_link_2`, `note_extra`, `note_extra_2`, `injuries_extra` are mapped. DB/UI use `muni_empl`. Duplicate Excel names are already disambiguated (`road_blocked` / `bridge_blocked`, separate damage-level fields).

**Spec vs. reality differences:**

- Spec: computed totals should be recalculated. Import copies `Total_D` / `Total_Inj` / section rollups **as-is** — no `compute_rollups()`.
- Spec: Automated geography from `villages` — **this part matches**.
- Spec: no incident export — matches (only a SQL view).
- Gate/DID rules are not applied on import.
- Spec open question #2 (Admin vs Super Admin import) — code is Super Admin only, matching current spec.

**Risk/quality notes:** Bad workbook totals persist. Import can create duplicates the pipeline would have merged. No `export_logs` table (listed in db.md as not present).

**Ideas to discuss:**

1. Run the same rollup + gate sanitizer on import as on live edit.
2. Decide whether incident export should wrap `incident_excel_view` or stay SQL-only.
3. Decide whether import may stay Super Admin-only (spec question 2).
4. Formalize extra columns (`Links__2`, extra Notes/Injuries) as adopted — they are already mapped.

---

## H. Sources & content-origin management flow

**Implementation found:** Configured sources `app/api/sources_router.py` (`GET /api/sources`, `POST .../pause|resume`); content origins `app/api/content_sources_router.py`; models `source.py`, `source_platform.py`, `content_source_block.py`; frontend **only** `SourcesPage.tsx` (content-source blocks). Pause/resume of `sources.is_active` has API + `useSetSourceActiveMutation` but **no UI**.

**How it actually works:** Both roles can list sources and block/unblock `(platform, account)`. Inactive `sources.is_active` stops poll/webhook ingest. Blocks increment `messages_blocked` on CNRS paths. Pause/resume writes `audit_logs`.

**Spec vs. reality differences:** Spec “View/pause/resume configured sources” is backend-complete and **frontend-missing**. The Sources page “Paused” filter means **content-source blocked**, not `sources.is_active`.

**Risk/quality notes:** Operators cannot pause CNRS or Red Alert from the UI without hitting the API. Terminology will train people to think “paused” means the connector is off.

**Ideas to discuss:**

1. Add a configured-sources panel (pause CNRS / Red Alert) distinct from per-account blocks.
2. Rename UI “Paused” to “Blocked origin” so it matches the table.
3. Show last ingestion health next to each source (join `ingestion_logs`).

---

## I. Logs & audit flow

**Implementation found:** `app/api/logs_router.py` — `/api/logs/audit`, `/login`, `/ingestion` (+ retry); writers in auth, ingest, accounts, sources, content-sources; `incident_updates` write-only; frontend `LogsPage.tsx` (audit / login / ingestion; Super Admin also Pipeline health). Manual sweep `POST /api/pipeline/sweep` Super Admin only — **no frontend button**. Accounts Super Admin only.

**How it actually works:** Both roles can view logs. Login logs default to **success only** unless `result=failure|all`. Ingestion retry exists. Pipeline tab is `GET /api/pipeline/health` (queue depths, cursor gap, latency) — not raw `pipeline_stage_runs`.

**Spec vs. reality differences:**

- `audit_logs` cover accounts, source pause/resume, content-source block — **not** incident edits, imports, duplicate resolutions, or ingestion retry.
- `incident_updates` is the incident audit trail but has **no read API or UI**.
- Spec: Super Admin triggers a manual sweep — API/CLI only.
- Extra: pipeline health tab; ingestion retry.

**Risk/quality notes:** Failed logins are hidden by the default login-log filter. `usePermissions.ts` is unused and wrongly limits logs/sources to Super Admin. `getLogs()`-style leftover would 404 if used.

**Ideas to discuss:**

1. Default login logs to `all` or add a clear Success/Failure toggle that is on by default for ops.
2. Add a Super Admin “Run sweep now” control on the Pipeline tab (the API already exists).
3. Surface `incident_updates` on the incident detail page so “everything traceable” is actually visible.
4. Delete or fix `usePermissions` before someone wires it.

---

## J. Operational flow

**Implementation found:** Docker `docker-compose.yml`: `backend`, `frontend`, `pipeline-worker`, `live-sweep-worker` (every 300s), **`backlog-relevance-worker`** (every 1800s, extra), `cnrs-poll-worker`, `red-alert-collector`, plus `db` and `redis`. Seeds: `app/core/seeds/seed_villages.py`, `seed_conditions.py` from `Data/Villages.json` / `Data/Conditions.json`; CNRS + super-admin seeds. Ollama caps in `app/core/ollama_concurrency.py`. Scheduler in `app/core/scheduler.py` (CNRS poll if `delivery_method != "webhook"`; red-alert loop **disabled** in the API container).

**How it actually works:** Manual sweep enqueues `pipeline_sweep_jobs` with advisory lock. Live sweep processes `raw_messages.id > sweep_cursors` without that lock. Workers reclaim stale advisory locks on startup. Reference data is operational load, not request-time. Redis caches villages/conditions/air-violation lists, not the job queue.

**Spec vs. reality differences:**

- Extra worker: backlog relevance.
- Extra Redis.
- `pipeline_sweep_jobs` is `CREATE TABLE IF NOT EXISTS` at runtime, not an Alembic revision.
- Telegram: enum exists; the only live Telegram path is Red Alert (`public_preview` scrape or optional Telethon). No generic Telegram news ingest (matches known gap #1, with Red Alert as the exception).
- Tables still absent: `incident_media`, `export_logs`, `field_definitions`.
- Extra enums in code: `message_status.materialized`, `match_status.insufficient_score`.

**Risk/quality notes:** CNRS can be polled by both the API scheduler and `cnrs-poll-worker` if `delivery_method` is mis-set. Pipeline jobs table can drift from migrations. Weak default secrets in `config.py`. Bootstrap endpoint is public on an empty database.

**Ideas to discuss:**

1. Put `pipeline_sweep_jobs` in Alembic so environments don’t rely on first-writer DDL.
2. Document the real worker set (including backlog-relevance) in the spec.
3. Known gap #1: keep Telegram enum + Red Alert only, or schedule a real Telegram ingest path.
4. Known gaps #3–4, #8: incident export, leftover workbook fields (`mjnoub`, `genocide`, `No_warning`/`Warning`) — still unresolved in product code.

---

## Overall

**Most solid:** Auth (A) and air-violation CRUD/export (F/G export side) are complete enough to operate. Incident detail editing (E) has real gate/DID logic and a usable UI. Pipeline concurrency (SKIP LOCKED + Ollama caps + session-closed LLM on tier1/tier2) is more mature than the spec implies.

**Thinnest / riskiest:**

- **Ingestion (B)** — three CNRS pollers, poll does not enqueue sweeps, Red Alert and webhooks log inconsistently.
- **Duplicates (D) + reconciliation (C10)** — many writers, one narrow review UI; `insufficient_score` is dead; clustering no longer soft-deletes but reconciliation still assumes it might.
- **Relevance uncertain → rejected (C1)** — largest behavioral break from the spec; Rejected News is the safety valve, not the pipeline.
- **Import (G)** — Super Admin bulk load with no duplicate checks and no rollup recalculation.
- **Sources UI (H)** — cannot pause the actual connectors.

**What I’d tackle first if we start building today:**

1. **Product-decide uncertain relevance** (proceed vs rejected-for-review vs new status) and write that into the spec so C1 stops being an accidental fork.
2. **One CNRS ingest path + sweep enqueue on poll**, so messages don’t sit in `pending` until live-sweep/backlog luck.
3. **A real duplicates inbox** (incident-to-incident *and* fast-path raw-message links) before adding more dedup layers.
4. **Import safety** (recompute totals, apply gates, optional duplicate check) before more workbook work.

**Secondary but cheap:** add `materialized` to the spec; wire or drop `insufficient_score`; add a Super Admin sweep button; put configured-source pause in the Sources UI; write `incident_updates` on delete/header edit.
