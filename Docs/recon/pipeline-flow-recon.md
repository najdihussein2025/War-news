# Pipeline Flow Recon

Date of recon: 2026-09-02

This report documents the pipeline as implemented in code today. I traced the worker entrypoints, orchestrator, per-stage services, repositories, relevant frontend read path, and the schema migrations that introduced the columns and indexes the flow depends on.

## 1. Stage inventory

### Actual stage order

The dedicated full sweep order is:

1. `relevance_filter`
2. `pre_extraction_dedup`
3. `tier1_extraction`
4. `matching`
5. `fast_path`
6. `tier2_detail_fill`
7. `embedding`
8. `clustering`
9. `materialization`

Source: `app/news/services/pipeline_orchestrator.py:150-329`, especially the ordered stage calls at `:204-268`.

### Doc mismatch vs current code

- `duplicate_match_reconciliation` is not a standalone orchestrated stage anymore. It is invoked inside `sweep_materialization()` after the per-row materialization loop finishes (`app/news/services/pipeline_sweep_stages.py:606-681`, reconciliation call at `:666`).
- There are effectively two runtime sweep flavors:
  - Manual/ops sweep: queued through `POST /api/pipeline/sweep`, claimed by the dedicated `pipeline-worker`, and optionally serialized with a session-level advisory lock (`app/api/pipeline_router.py:13-25`, `app/core/scripts/run_pipeline_worker.py:36-71`, `app/news/services/pipeline_orchestrator.py:37-51`, `:150-190`).
  - Live sweep: `scripts/live_sweep_new_only.py` runs every 300 seconds in Docker, advances a persisted raw-message cursor after relevance, and caps every downstream stage at `100` rows per pass (`docker-compose.yml:83-98`, `scripts/live_sweep_new_only.py:43`, `:56`, `:639-744`).

## 2. Per-stage deep dive

### Stage: `relevance_filter`

- Trigger
  - Manual sweep path: orchestrated first in `run_full_pipeline_sweep()` (`app/news/services/pipeline_orchestrator.py:204-206`).
  - Live sweep path: first stage in `scripts/live_sweep_new_only.py`, but only for rows with `RawMessage.id > cutoff_raw_message_id`; the cursor is advanced immediately after this stage (`scripts/live_sweep_new_only.py:633`, `:639-654`).
  - Backlog sweep path: `scripts/backlog_relevance_sweep.py` runs only relevance, no cursor gate, on a slower cadence (`scripts/backlog_relevance_sweep.py:27-28`, `:49-58`; Docker cadence `docker-compose.yml:103-118`).
  - CNRS polling and Red Alert collection do not run relevance themselves; they only ingest new `raw_messages` in `status='pending'` (`scripts/cnrs_poll_worker.py:146-264`, `app/core/scripts/run_red_alert_collector.py:66-112`).
- Claim / locking
  - Batch selection is `RawMessageRepository.get_pending_unfiltered_batch()` with `SELECT ... FOR UPDATE SKIP LOCKED` on `status = pending AND filter_result IS NULL`, ordered by ascending `id` (`app/news/repositories/raw_message_repository.py:39-53`).
  - Manual sweep advisory lock is around the whole sweep, not this query specifically (`app/news/services/pipeline_orchestrator.py:37-51`, `:180-190`).
  - Live sweep additionally monkey-patches the repository so the query includes `RawMessage.id > cutoff_raw_message_id` (`scripts/live_sweep_new_only.py:151-174`, `:351-369`).
- Batch size / row cap
  - DTO default request size is `200` (`app/llm/dtos/relevance_filter_dto.py:25`).
  - `FilterRelevanceAction` further chunks LLM candidates by `settings.relevance_llm_batch_size`, default `4` (`app/api/factories/action_factory.py:71-82`, `app/core/config.py:45`, `app/llm/actions/filter_relevance_action.py:154-159`).
  - Manual full sweep has no hardcoded stage cap unless `max_rows` is passed at the sweep level (`app/news/services/pipeline_orchestrator.py:150-329`).
  - Live sweep does not cap relevance with `STAGE_MAX_ROWS_PER_PASS`; it only caps downstream stages. It stops when no more rows above the cursor are available (`scripts/live_sweep_new_only.py:56`, `:639-654`).
- LLM usage
  - Backend selection is `settings.relevance_classifier_backend`, default `cnrs_provided` (`app/core/config.py:47`, `app/api/factories/action_factory.py:28-51`).
  - If fallback/local LLM is used, it is `LocalLLMRelevanceClassifier` with model `settings.relevance_ollama_model` and timeout `settings.relevance_llm_timeout_seconds` (`app/api/factories/action_factory.py:13-26`, `app/core/config.py:39`, `:46`).
  - Local relevance retries are classifier-level retries: `max_retries=3`, exponential backoff from `1.0s` (`app/core/config.py:48-49`, `app/llm/services/local_llm_relevance_classifier.py:98-114`, `:121-147`).
  - The prompt is inline in `RELEVANCE_CLASSIFICATION_PROMPT`; there is no external prompt-template file for this stage (`app/llm/services/local_llm_relevance_classifier.py:24-55`).
- Non-LLM logic
  - Trusted sources bypass LLM and are marked relevant directly when `source.config["trusted"] is True` (`app/llm/actions/filter_relevance_action.py:79-109`).
  - CNRS-provided classification also bypasses the LLM when `include` is boolean or `event_domain` and `event_subtype` are present (`app/llm/services/cnrs_relevance_classifier.py:15-38`, `:41-67`; use in action at `app/llm/actions/filter_relevance_action.py:113-138`).
  - Keyword prefilter auto-rejects rows without village/action candidate keywords before any classifier call (`app/llm/actions/filter_relevance_action.py:140-151`).
- DB writes / status transitions
  - `save_filter_result()` writes `raw_messages.filter_result`, `status`, `low_confidence_relevance`, clears claim metadata, and commits (`app/news/repositories/raw_message_repository.py:75-90`).
  - Verdict mapping is:
    - relevant -> `status='parsed'`
    - not relevant -> `status='rejected'`
    - uncertain -> `status='rejected'` plus `needs_review=True`
    (`app/llm/services/relevance_filter_service.py:9-28`).
  - Failures write `status='error'` via `save_error()` (`app/news/repositories/raw_message_repository.py:142-151`).
- Failure handling
  - Chunk failures are retried once inside `FilterRelevanceAction.execute_async()`; if the retry also fails, every row in the chunk is marked `error` (`app/llm/actions/filter_relevance_action.py:163-207`).
  - Ollama auth failures are coerced and abort the stage/sweep (`app/llm/actions/filter_relevance_action.py:167-172`, `:186-191`; sweep abort handling in `app/news/services/pipeline_sweep_stages.py:107-123` and `app/news/services/pipeline_orchestrator.py:214-221`).
  - This stage does implement the auth-abort behavior.
- Timing
  - Code records only stage-level elapsed seconds in the returned `StageSweepResult`; there is no per-row or persisted stage timing table (`app/news/dtos/pipeline_dto.py:4-18`, `app/news/services/pipeline_sweep_stages.py:86-127`).
  - I could not sample DB-backed timing because a direct local query failed: the configured DB host is `db` from Docker Compose and is not resolvable from this shell (`docker-compose.yml:2`, local probe on 2026-09-02 returned `psycopg2.OperationalError: could not translate host name "db"`).
- Bottleneck risk
  - This stage processes the fetched message list sequentially inside the action, but LLM work is batched at up to `4` messages per classifier call by default (`app/llm/actions/filter_relevance_action.py:154-159`, `app/core/config.py:45`).
  - DB sessions are held while saving results, but the LLM call itself happens from the action against loaded ORM rows; unlike extraction, there is no explicit “no DB session held during LLM call” worker wrapper here.

### Stage: `pre_extraction_dedup`

- Trigger
  - Second stage in both the dedicated full sweep and the live sweep (`app/news/services/pipeline_orchestrator.py:223-225`, `scripts/live_sweep_new_only.py:660-665`).
- Claim / locking
  - Dedicated concurrent worker claims one row at a time with `claim_pending_pre_dedup()`: `status='parsed' AND extraction_result IS NULL AND duplicate_of_id IS NULL`, ordered by ascending `id`, `FOR UPDATE SKIP LOCKED` (`app/news/repositories/pipeline_claim_repository.py:76-87`).
  - The actual similarity lookup is a separate query using `word_similarity(raw_messages.raw_text, :raw_text)` against other rows received within the last 48 hours (`app/news/services/pre_extraction_dedup.py:52-80`).
- Batch size / row cap
  - Manual sync sweep default batch size is `50` because `DEFAULT_BATCH_SIZE = ExtractPendingMessagesData().batch_size` (`app/news/services/pipeline_sweep_stages.py:31`, `app/llm/dtos/extraction_dto.py:140`).
  - Concurrent/live implementation applies `_effective_pre_dedup_max_rows()`: explicit `max_rows` if passed, otherwise `settings.pre_dedup_sweep_row_cap`, default `100` (`app/news/services/pipeline_concurrent_sweeps.py:133-136`, `app/core/config.py:70`).
  - Rows beyond the cap wait for the next sweep pass.
- LLM usage
  - None.
- Non-LLM logic
  - Similarity threshold is `settings.pre_dedup_similarity_threshold`, default `0.92` (`app/core/config.py:67`, `app/news/services/pipeline_concurrent_sweeps.py:189`, `app/news/services/pipeline_sweep_stages.py:142`).
  - Lookback window is hardcoded to `INTERVAL '48 hours'` on `received_at` (`app/news/services/pre_extraction_dedup.py:73`).
  - Comparison set explicitly excludes `rejected`, `duplicate`, and `materialized` rows, but not plain `parsed` rows or `error` rows (`app/news/services/pre_extraction_dedup.py:65-72`).
  - Canonical original is always the lower `raw_message.id`; two-cycle targets are rejected (`app/news/services/pre_extraction_dedup.py:13-20`, `:29-49`).
- DB writes / status transitions
  - If matched above threshold, the candidate row is updated in place to `status='duplicate'` and `duplicate_of_id=<original_id>` (`app/news/services/pre_extraction_dedup.py:125-131`).
  - Otherwise the row is left untouched.
- Failure handling
  - Exceptions roll back the row transaction and increment `failed`; there is no retry queue (`app/news/services/pipeline_concurrent_sweeps.py:207-217`).
  - No auth/circuit-break logic is needed because no LLM is called.
- Timing
  - No persisted per-row instrumentation. Only stage-level elapsed seconds are recorded.
  - Tests confirm the 48-hour window and exclusion of `materialized` rows, but do not provide runtime timings (`tests/test_pre_extraction_dedup.py`).
- Bottleneck risk
  - Work is parallelized up to `settings.ollama_max_concurrent_requests` worker tasks even though no LLM is involved (`app/news/services/pipeline_concurrent_sweeps.py:233-239`, worker count from `:97-99`, config `app/core/config.py:38`).
  - Each row still does a similarity query; on large parsed backlogs this is DB-heavy, which is why the live sweep caps it at `100`.

### Stage: `tier1_extraction`

- Trigger
  - Third stage in both the dedicated full sweep and the live sweep (`app/news/services/pipeline_orchestrator.py:227-235`, `scripts/live_sweep_new_only.py:668-676`).
- Claim / locking
  - One-row claim via `claim_pending_extraction()`, requiring `status='parsed' AND extraction_result IS NULL AND duplicate_of_id IS NULL`, plus lease reuse rules on `processing_claimed_at` / `processing_claim_stage`; query is ordered by descending `id` and uses `FOR UPDATE SKIP LOCKED` (`app/news/repositories/pipeline_claim_repository.py:37-52`, `:89-103`).
  - Claim lease timeout is `settings.pipeline_claim_lease_seconds`, default `240` (`app/core/config.py:79`, `app/news/repositories/pipeline_claim_repository.py:27-31`).
- Batch size / row cap
  - Legacy/sync action batch size default is `50` (`app/llm/dtos/extraction_dto.py:140`, `app/news/services/pipeline_sweep_stages.py:152-205`).
  - Current concurrent sweep runs until empty unless `max_rows` is passed; live sweep passes `STAGE_MAX_ROWS_PER_PASS = 100` (`app/news/services/pipeline_concurrent_sweeps.py:323-359`, `scripts/live_sweep_new_only.py:56`, `:672-674`).
- LLM usage
  - Classifier is `OllamaExtractionService` built around `OllamaChatClient` (`app/api/factories/action_factory.py:85-97`).
  - Model is `settings.extraction_ollama_model`, default `qwen2.5:7b` (`app/core/config.py:40`).
  - Timeout is `settings.extraction_llm_timeout_seconds`, default `240` (`app/core/config.py:41`, `app/api/factories/action_factory.py:91`).
  - HTTP retries inside the client are `settings.extraction_llm_request_retries`, default `2`, with `settings.extraction_llm_retry_backoff_seconds`, default `2.0s` (`app/core/config.py:43-44`, `app/api/factories/action_factory.py:92-95`, `app/core/ollama_client.py:89-138`).
  - Shared concurrency limit is `settings.extraction_llm_max_concurrent_requests`, default `2`, enforced via `run_with_ollama_limit()` (`app/core/config.py:42`, `app/news/services/pipeline_concurrent_sweeps.py:273-276`, `app/core/ollama_concurrency.py:9-39`).
  - Tier 1 actually makes two LLM calls per row:
    - presence gate prompt from `scripts/phase2-extraction-testing/presence_gate_instruction.txt` via `PROMPT_PATH` (`app/llm/services/ollama_presence_gate_service.py:85-91`, call path `:172-182`);
    - general extraction prompt is inline `GENERAL_EXTRACTION_PROMPT`, not an external file (`app/llm/services/ollama_extraction_service.py:31-94`, call path `:324-333`).
- Non-LLM logic
  - Root extraction payload stores only general fields plus `presence_category_keys` and root casualties in Tier 1 (`app/llm/services/ollama_extraction_service.py:126-162`, `app/llm/dtos/extraction_dto.py:83-97`).
  - Malformed JSON from either presence gate or general extraction raises `RuntimeError("Malformed ... response.")` (`app/llm/services/ollama_presence_gate_service.py:196-208`, `app/llm/services/ollama_extraction_service.py:339-352`).
- DB writes / status transitions
  - Successful extraction writes `raw_messages.extraction_result`, clears claim metadata, resets `extraction_retry_count`, and commits; `status` remains `parsed` (`app/news/repositories/raw_message_repository.py:92-103`).
  - The migration for `raw_messages.extraction_result` is `20260811_0008` and for `raw_messages.extraction_retry_count` is `20260819_0025` (`alembic/migration/20260811_0008_add_raw_message_extraction_result.py:19-26`, `alembic/migration/20260819_0025_add_raw_messages_extraction_retry_count.py:18-29`).
- Failure handling
  - `run_tier1_extraction_for_message()` explicitly avoids holding a DB session during the Ollama calls by loading the text, closing that DB scope, calling the classifier, then reopening a session to persist (`app/news/services/pipeline_llm_workers.py:20-41`, `:95-104`).
  - Auth failures are coerced to `OllamaAuthFailure` and abort the stage (`app/news/services/pipeline_llm_workers.py:45-50`, sweep abort in `app/news/services/pipeline_concurrent_sweeps.py:351-358`).
  - Transient LLM/network errors increment `extraction_retry_count`, park the row in `status='error'`, and later sweeps re-queue it until `settings.extraction_max_retries`, default `5` (`app/news/services/pipeline_llm_workers.py:51-69`, `app/news/repositories/raw_message_repository.py:153-189`, `:191-247`, `app/core/config.py:80`).
  - Non-transient failures mark the row `error` immediately (`app/news/services/pipeline_llm_workers.py:71-82`).
- Timing
  - No persisted per-row timings.
  - There are only benchmark scripts, not production instrumentation, for presence-gate timing and batch throughput (`scripts/phase2-extraction-live-check/benchmark_presence_gate_http_timing.py`, `scripts/phase2-extraction-live-check/benchmark_tier1_batch_throughput.py`).
- Bottleneck risk
  - This is the most expensive stage in comments and design notes. The live sweep hard-cap exists specifically to prevent extraction backlog starvation of later stages (`scripts/live_sweep_new_only.py:45-56`).
  - Good news: this stage does satisfy the “LLM work must not hold database sessions” rule in the concurrent worker path (`app/news/services/pipeline_llm_workers.py:20-41`).

### Stage: `matching`

- Trigger
  - Fourth stage in both sweep flavors (`app/news/services/pipeline_orchestrator.py:241-244`, `scripts/live_sweep_new_only.py:681-689`).
- Claim / locking
  - One-row claim via `claim_pending_match()`: `status='parsed' AND extraction_result IS NOT NULL AND match_result IS NULL AND duplicate_of_id IS NULL`, descending `id`, `FOR UPDATE SKIP LOCKED`, with the same 240-second lease reuse logic (`app/news/repositories/pipeline_claim_repository.py:37-52`, `:105-120`).
- Batch size / row cap
  - Legacy sync sweep default batch size is `50` (`app/news/services/pipeline_sweep_stages.py:208-279`, `app/llm/dtos/extraction_dto.py:140`).
  - Current live sweep passes `max_rows=100`; dedicated manual sweep is unbounded unless the queued job includes `limit` (`scripts/live_sweep_new_only.py:56`, `:685-687`, `app/api/pipeline_router.py:13-25`).
- LLM usage
  - None.
- Non-LLM logic
  - Village matching threshold is `0.6`; low-confidence threshold is `0.35` (`app/news/services/matching_service.py:33-34`).
  - Village and condition matching both use trigram similarity via repository `find_similar()` methods (`app/news/repositories/village_repository.py:42-61`, `app/news/repositories/condition_repository.py:22-41`).
  - Condition matching has hardcoded distinguishing-token guards for condition ids `2` and `39` (`app/news/services/matching_service.py:36-39`, `:126-131`).
- DB writes / status transitions
  - `MatchIncidentAction.execute()` validates `extraction_result`, computes `match_result`, routes air violations before marking matching complete, then writes `raw_messages.match_result` and clears claim metadata (`app/news/actions/match_incident_action.py:21-47`, `app/news/repositories/raw_message_repository.py:118-128`).
  - `raw_messages.match_result` was added in `20260813_0013` (`alembic/migration/20260813_0013_add_raw_message_match_result.py:18-25`).
- Failure handling
  - Matching failures increment `match_retry_count`, set `status='error'`, and are re-queued later until `settings.matching_max_retries`, default `5` (`app/news/repositories/raw_message_repository.py:249-277`, `:279-329`, `app/core/config.py:81`).
  - The concurrent worker releases the claim if the row has become ineligible rather than leaving the lease behind (`app/news/services/pipeline_concurrent_sweeps.py:394-418`).
  - No LLM auth/circuit-break logic is needed here.
- Timing
  - No persisted timing instrumentation.
- Bottleneck risk
  - CPU/DB bound rather than LLM bound. Matching is parallelized with `_worker_count()`, which uses `settings.ollama_max_concurrent_requests` even though the stage is not calling Ollama (`app/news/services/pipeline_concurrent_sweeps.py:97-99`, `:423-442`).

### Stage: `fast_path`

- Trigger
  - Fifth stage in both sweep flavors (`app/news/services/pipeline_orchestrator.py:246-249`, `scripts/live_sweep_new_only.py:692-700`).
- Claim / locking
  - Claims `status='parsed' AND duplicate_of_id IS NULL AND match_result IS NOT NULL AND extraction_result IS NOT NULL`, with no active incident yet, plus `fast_path_materializable_clause()`, ordered ascending `id`, `FOR UPDATE SKIP LOCKED` (`app/news/repositories/pipeline_claim_repository.py:122-145`).
  - For each materializable village+condition pair, the service acquires `pg_advisory_xact_lock(village_id, condition_id)` to protect the check-then-insert window (`app/news/services/incident_materialization_service.py:116-122`, `app/news/services/pipeline_advisory_lock.py:15-28`).
- Batch size / row cap
  - Current live sweep passes `max_rows=100` (`scripts/live_sweep_new_only.py:56`, `:696-698`).
  - Before worker tasks start, the sweep terminalizes permanently ineligible rows in bulk (`app/news/services/pipeline_concurrent_sweeps.py:506-517`).
- LLM usage
  - None.
- Non-LLM logic
  - Eligible village/condition match statuses are `matched` or `matched_low_confidence`, but the duplicate short-circuit requires both village and condition to be exactly `matched` (`app/news/services/fast_path_dedup.py:30-31`, `:57-67`).
  - Fast-path duplicate window is exact same `village_id + condition_id` within `settings.fast_dedup_time_window_minutes`, default `120` minutes (`app/core/config.py:66`, `app/news/services/fast_path_dedup.py:60-64`, `app/news/repositories/incident_repository.py:665-693`).
  - Air-violation conditions are hardcoded ids `{35, 36, 38, 45}` (`app/news/services/fast_path_eligibility.py:10`, `:87-102`).
  - Materializability SQL is explicit JSONB logic in `FAST_PATH_MATERIALIZABLE_SQL`, not repository inference (`app/news/services/fast_path_eligibility.py:20-54`).
- DB writes / status transitions
  - If every village is a confident duplicate, the raw message becomes `status='duplicate'`, `duplicate_of_id=<representative_raw_message_id>`, and a `duplicate_matches` row is written with `raw_message_id` populated and `matched_incident_id=NULL` (`app/news/services/incident_materialization_service.py:147-166`, `:185-197`; `app/news/repositories/incident_repository.py:567-583`; migration `alembic/migration/20260824_0032_allow_fast_path_duplicate_matches.py:24-49`).
  - If materialized, the service inserts an `incidents` row plus a minimal `incident_details` row and sets `raw_messages.status='materialized'`; these incidents are created with `details_pending=True` (`app/news/services/incident_materialization_service.py:242-300`, `_mark_materialized()` at `:233-236`).
  - If ineligible, the raw message is terminalized to `status='error'` or `status='routed_air_violation'` with an explanatory `error_message` (`app/news/services/incident_materialization_service.py:217-231`).
  - `message_status.materialized` was added in `20260827_0035`; processing claim fields in `20260827_0036` (`alembic/migration/20260827_0035_add_materialized_message_status.py:18-21`, `alembic/migration/20260827_0036_add_raw_message_processing_claims.py:18-35`).
- Failure handling
  - No retries; exceptions roll back the unit of work and the row will remain claimable later (`app/news/services/pipeline_concurrent_sweeps.py:475-497`).
  - Exact-hash uniqueness collisions are treated as skip/terminalization, not hard failures (`app/news/services/incident_materialization_service.py:302-314`).
- Timing
  - No persisted timing instrumentation.
- Bottleneck risk
  - Parallelized worker loop, but still transaction-heavy because it takes advisory xact locks and commits per village/incident decision.
  - No LLM involved, so DB is the main risk.

### Stage: `tier2_detail_fill`

- Trigger
  - Sixth stage in both sweep flavors (`app/news/services/pipeline_orchestrator.py:251-258`, `scripts/live_sweep_new_only.py:703-711`).
  - It is driven by `Incident.details_pending = true`, not directly by raw-message status (`app/news/repositories/pipeline_claim_repository.py:175-183`).
- Claim / locking
  - Claims one incident row with `details_pending IS TRUE AND is_deleted IS FALSE`, oldest `created_at` first, `FOR UPDATE SKIP LOCKED` (`app/news/repositories/pipeline_claim_repository.py:175-183`).
  - The worker converts that to `(incident_id, raw_message_id)` and then calls `run_tier2_detail_fill_for_message(raw_message_id)` (`app/news/services/pipeline_concurrent_sweeps.py:116-131`, `:541-569`).
- Batch size / row cap
  - Dedicated full sweep is unbounded unless `max_rows` is passed.
  - Live sweep passes `100` (`scripts/live_sweep_new_only.py:56`, `:707-709`).
  - Because one raw message can own multiple incidents, “100 claimed incidents” is the actual bound, not “100 raw messages.”
- LLM usage
  - Uses the same `OllamaExtractionService` and `OllamaChatClient` as Tier 1 (`app/news/services/pipeline_llm_workers.py:112-125`).
  - The stage calls per-category detail extraction only when stored `extraction_tier < 2` (`app/news/services/pipeline_llm_workers.py:123-134`, `app/news/services/tier2_detail_fill_service.py:41-54`).
  - Category detail prompt is external: `scripts/phase2-extraction-testing/category_detail_instruction.txt` via `PROMPT_PATH` (`app/llm/services/ollama_category_detail_service.py:22-28`, call at `:85-103`).
  - Category detail extraction shares the same extraction model, timeout, client retries, and concurrency limit as Tier 1 (`app/api/factories/action_factory.py:85-97`, `app/core/config.py:40-44`, `app/news/services/pipeline_concurrent_sweeps.py:555-558`).
- Non-LLM logic
  - `Tier2DetailFillService.apply_tier2_result_for_raw_message()` merges the returned Tier 2 categories into the stored `raw_messages.extraction_result`, computes mapped detail fields, computes total casualty rollups, generates a raw-message embedding if one is still missing, updates each `details_pending` incident for that raw message, and sets `details_pending=False` (`app/news/services/tier2_detail_fill_service.py:59-149`).
  - This stage can also perform an embedding-based dedup backstop and merge the just-filled incident into another existing incident if the score crosses `dedup_high_threshold` (`app/news/services/tier2_detail_fill_service.py:153-194`).
- DB writes / status transitions
  - Writes back `raw_messages.extraction_result` with `extraction_tier=2` when tier2 categories were supplied (`app/news/services/tier2_detail_fill_service.py:89-101`).
  - Updates `incidents.total_deaths`, `incidents.total_injuries`, `incidents.khabar_embedding`, and `incidents.details_pending=False`; updates/inserts `incident_details`; may set `incident.duplicate_flag=True` or `incident.is_deleted=True` in dedup backstop cases (`app/news/services/tier2_detail_fill_service.py:103-149`, `:173-195`).
  - `details_pending` was added in `20260818_0024` (`alembic/migration/20260818_0024_add_incidents_details_pending.py:18-29`).
- Failure handling
  - `run_tier2_detail_fill_for_message()` avoids holding the DB session during the LLM call by loading the raw message first, closing that scope, making the LLM call, then reopening a session to persist (`app/news/services/pipeline_llm_workers.py:106-145`).
  - Auth failures are coerced and abort the stage (`app/llm/services/ollama_extraction_service.py:177-186`, `:249-258`; sweep abort in `app/news/services/pipeline_concurrent_sweeps.py:602-609`).
  - Per-category detail failures are logged and skipped; the service still persists whatever categories succeeded (`app/llm/services/ollama_extraction_service.py:175-208`).
  - There is no dedicated retry queue for Tier 2 incidents. Failed rows simply remain `details_pending=true`.
- Timing
  - No persisted timing instrumentation.
- Bottleneck risk
  - This stage satisfies the “no DB session held during LLM call” rule in the concurrent worker path (`app/news/services/pipeline_llm_workers.py:106-145`).
  - It may do a second expensive operation even on non-LLM paths because it can generate embeddings inline if the embedding stage has not run yet (`app/news/services/tier2_detail_fill_service.py:113-117`).

### Stage: `embedding`

- Trigger
  - Seventh stage in both sweep flavors (`app/news/services/pipeline_orchestrator.py:266-268`, `scripts/live_sweep_new_only.py:716-724`).
- Claim / locking
  - No claim lease repository is used. The sync sweep simply selects ascending `RawMessage.id` where `status='parsed' AND content_embedding IS NULL`, then loops sequentially (`app/news/services/pipeline_sweep_stages.py:381-442`).
  - Important behavior: because it filters on `status='parsed'`, fast-path materialized rows are excluded from this stage. Tier 2 compensates by generating the embedding itself if needed (`app/news/services/pipeline_sweep_stages.py:405-414`, `app/news/services/tier2_detail_fill_service.py:113-117`).
- Batch size / row cap
  - Default batch size is `50` (`app/news/services/pipeline_sweep_stages.py:381-442`, `app/llm/dtos/extraction_dto.py:140`).
  - Live sweep caps this stage at `100` rows per pass (`scripts/live_sweep_new_only.py:56`, `:720-722`).
- LLM usage
  - None. Embeddings are local sentence-transformer embeddings using model `paraphrase-multilingual-MiniLM-L12-v2` (`app/news/services/embedding_service.py:5-13`).
- Non-LLM logic
  - Boilerplate stripping happens before encoding via `RawMessageEmbeddingService.strip_boilerplate()` (`app/news/services/raw_message_embedding_service.py:40-49`).
- DB writes / status transitions
  - Writes `raw_messages.content_embedding` and commits; no status change (`app/news/repositories/raw_message_repository.py:130-140`).
  - `raw_messages.content_embedding` and its HNSW index came from `20260814_0018` (`alembic/migration/20260814_0018_add_raw_message_duplicate_clustering.py:25-38`).
- Failure handling
  - Exceptions roll back and increment `failed`; there is no retry queue (`app/news/services/pipeline_sweep_stages.py:424-433`).
- Timing
  - No persisted timing instrumentation.
- Bottleneck risk
  - Entirely sequential inside the stage loop.

### Stage: `clustering`

- Trigger
  - Eighth stage in both sweep flavors (`app/news/services/pipeline_orchestrator.py:266-268`, `scripts/live_sweep_new_only.py:727-735`).
- Claim / locking
  - No per-row claim. The stage loads all currently eligible `RawMessage` rows up to `max_rows` and clusters them in memory (`app/news/services/pipeline_sweep_stages.py:456-484`, `:486-603`).
- Batch size / row cap
  - There is no batch size beyond the optional `max_rows` query limit.
  - Live sweep passes `100`; dedicated manual sweep can load all eligible rows into memory (`scripts/live_sweep_new_only.py:731-733`, `app/news/services/pipeline_orchestrator.py:266-268`).
- LLM usage
  - None.
- Non-LLM logic
  - Eligibility requires `status='parsed'`, `content_embedding IS NOT NULL`, `match_result IS NOT NULL`, and `duplicate_of_id IS NULL` (`app/news/services/pipeline_sweep_stages.py:467-474`).
  - Similarity threshold is `settings.cluster_similarity_threshold`, default `0.75`; time window is `settings.cluster_time_window_minutes`, default `300`; condition match is required by default (`app/core/config.py:62-64`, `app/news/services/clustering_service.py:120-140`, `:191-202`).
  - Candidate pairing requires at least one shared village id and message-datetime proximity within the window (`app/news/services/clustering_service.py:248-259`).
  - Representative selection prefers higher trust tiers, then earlier time, then lower id (`app/news/services/clustering_service.py:204-216`).
- DB writes / status transitions
  - Representative is materialized first.
  - Fully subsumed members are marked `raw_messages.status='duplicate'`, `duplicate_of_id=<representative_id>`, and their incidents are soft-deleted (`app/news/services/pipeline_sweep_stages.py:522-556`, `app/news/repositories/raw_message_repository.py:345-377`, `app/news/repositories/incident_repository.py:697-727`).
  - Partial village overlaps soft-delete only the affected incident rows and create `duplicate_matches` where possible (`app/news/services/pipeline_sweep_stages.py:557-585`, `app/news/repositories/incident_repository.py:729-760`).
- Failure handling
  - Cluster-level exceptions roll back the whole cluster and count every row in that cluster as failed (`app/news/services/pipeline_sweep_stages.py:591-600`).
- Timing
  - No persisted timing instrumentation.
- Bottleneck risk
  - O(n^2) in-memory pair comparison inside `cluster_batch()` (`app/news/services/clustering_service.py:218-246`).
  - This can become expensive quickly if manual sweeps run it unbounded.

### Stage: `materialization`

- Trigger
  - Final orchestrated stage in both sweep flavors (`app/news/services/pipeline_orchestrator.py:266-268`, `scripts/live_sweep_new_only.py:738-746`).
- Claim / locking
  - No lease claim repository is used. The stage selects ascending `RawMessage` rows where `status='parsed' AND duplicate_of_id IS NULL AND match_result IS NOT NULL`, limited by batch size / max_rows, and materializes sequentially (`app/news/services/pipeline_sweep_stages.py:606-664`).
  - This means it revisits rows already touched by fast path only if they are still `status='parsed'`; fast-path-created `materialized` rows are skipped.
- Batch size / row cap
  - Default batch size is `50` (`app/news/services/pipeline_sweep_stages.py:606-664`, `app/llm/dtos/extraction_dto.py:140`).
  - Live sweep caps it at `100` rows per pass (`scripts/live_sweep_new_only.py:56`, `:742-744`).
- LLM usage
  - None.
- Non-LLM logic
  - Exact-hash uniqueness is enforced by `uq_incidents_exact_hash_active` (`alembic/migration/20260811_0007_add_incidents_incident_details.py:98-103`, exact-hash conflict handling in `app/news/services/incident_materialization_service.py:497-514`).
  - Incident-level dedup uses `DedupMatchingService`, with weights:
    - action match `0.35`
    - embedding similarity `0.45`
    - time closeness `0.20`
    (`app/news/services/dedup_matching_service.py:10-18`).
  - Dedup lookback is `settings.dedup_time_window_days`, default `3`; thresholds are `0.80` high / merge and `0.50` low / flag (`app/core/config.py:73-75`, `app/news/services/dedup_matching_service.py:29-41`, `app/news/services/incident_materialization_service.py:417-455`).
- DB writes / status transitions
  - If merge score >= `dedup_high_threshold`, `IncidentRepository.merge_existing()` updates the existing incident’s casualty totals and details, appends a note referencing the new raw message, and writes an `incident_updates` row with `action='pipeline_merge'` (`app/news/services/incident_materialization_service.py:417-441`, `app/news/repositories/incident_repository.py:586-641`).
  - If score >= `dedup_low_threshold` but below high threshold, the new incident is inserted with `duplicate_flag=true` (`app/news/services/incident_materialization_service.py:442-455`, `:457-496`).
  - On successful insert, the raw message becomes `status='materialized'` (`app/news/services/incident_materialization_service.py:493`).
  - After the loop, `reconcile_orphaned_soft_deleted_incidents()` backfills missing `duplicate_matches` for already-soft-deleted incidents (`app/news/services/pipeline_sweep_stages.py:666-680`, `app/news/services/duplicate_match_reconciliation.py:53-87`).
- Failure handling
  - No retries. Per-row failures roll back and increment `failed` (`app/news/services/pipeline_sweep_stages.py:649-659`).
  - No auth/circuit-break logic is needed because no LLM is called.
- Timing
  - No persisted timing instrumentation.
- Bottleneck risk
  - Sequential stage.
  - Dedup correctness depends on embeddings existing. A row with no embedding can still be materialized, but then it cannot merge into an existing incident during this stage because `self.dedup_service is not None and khabar_embedding is not None` is required (`app/news/services/incident_materialization_service.py:407-455`).

## 3. End-to-end latency table

Because I could not connect from this shell to the configured Postgres host `db`, and the code does not persist per-stage per-row timings, I cannot provide trustworthy empirical timings for “typical” or “worst case” rows. The only production timing artifact in code is stage-level `elapsed_seconds` returned at runtime, not persisted in a queryable table (`app/news/dtos/pipeline_dto.py:4-18`).

| Stage | Typical per-row time | Typical per-batch time | Cumulative best case | Worst case |
| --- | --- | --- | --- | --- |
| `relevance_filter` | Not verifiable from code alone | Not verifiable | Not verifiable | Not verifiable |
| `pre_extraction_dedup` | Not verifiable | Not verifiable | Not verifiable | Not verifiable |
| `tier1_extraction` | Not verifiable in production data; benchmark scripts exist only | Not verifiable | Not verifiable | Not verifiable |
| `matching` | Not verifiable | Not verifiable | Not verifiable | Not verifiable |
| `fast_path` | Not verifiable | Not verifiable | Best-case incident can exist after this stage if fast-path inserts succeed | Worst case deferred to later sweeps if row remains parsed/error |
| `tier2_detail_fill` | Not verifiable | Not verifiable | Details can complete here for fast-path-created incidents | Failures leave `details_pending=true` |
| `embedding` | Not verifiable | Not verifiable | Not needed for fast-path existence of incident row | Needed for later incident-level dedup/clustering |
| `clustering` | Not verifiable | Not verifiable | May soft-delete duplicates after incident creation | O(n^2) cluster pass can delay large sweeps |
| `materialization` | Not verifiable | Not verifiable | Best-case non-fast-path incident exists after this stage | Merge/flag/exact-hash skip behavior depends on embeddings and dedup score |

## 4. Multi-day follow-up / incident-update question

### Short answer

There is a partial automated update path, but only for follow-up messages that survive pre-dedup, get extracted/matched, already have an embedding by the time full materialization or Tier 2 dedup backstop runs, and score above the incident-level dedup high threshold. Fast-path duplicate linking by itself does **not** merge updated casualty or asset numbers into the existing incident row.

### What pre-extraction dedup does to a Day-2/Day-3 follow-up

- It compares raw text to other non-rejected, non-duplicate, non-materialized messages from the last 48 hours using `word_similarity` and threshold `0.92` (`app/news/services/pre_extraction_dedup.py:52-80`, threshold from `app/core/config.py:67`).
- That means a follow-up message only gets caught here if its text is still extremely similar and the prior comparable message is inside the 48-hour `received_at` window.
- If the wording changed substantially because casualty numbers changed or new detail was added, this stage will often miss it and let it continue downstream.

### What fast-path does to a follow-up

- Fast-path only performs a duplicate short-circuit when both village and condition are confidently `matched` and there is an active incident for the same `village_id + condition_id` within `120` minutes (`app/news/services/fast_path_dedup.py:57-75`, `app/core/config.py:66`, `app/news/repositories/incident_repository.py:665-693`).
- If that window match hits, the code writes a `duplicate_matches` row via `create_fast_path_duplicate_match()` and may mark the raw message `duplicate_of_id=<representative_raw_message_id>` if all villages hit the duplicate path (`app/news/services/incident_materialization_service.py:147-166`, `:185-197`; `app/news/repositories/incident_repository.py:567-583`).
- That fast-path duplicate record does **not** call `merge_existing()`. So on its own it does not update `incidents.total_deaths`, `total_injuries`, or `incident_details.*`.

### What full materialization / incident-level dedup does to a follow-up

- If the follow-up survives fast path and reaches full `materialize()`, then for each village it can search for an existing incident within `dedup_time_window_days = 3` using embedding similarity plus action/time weighting (`app/news/services/dedup_matching_service.py:29-41`, `:73-94`, config `app/core/config.py:73-75`).
- If the score is >= `0.80`, `DedupMatchingService.merge_into_incident()` calls `IncidentRepository.merge_existing()` (`app/news/services/incident_materialization_service.py:417-441`, `app/news/services/dedup_matching_service.py:63-70`).
- `merge_existing()` does automatically update:
  - `incidents.deaths`
  - `incidents.injuries`
  - `incidents.total_deaths`
  - `incidents.total_injuries`
  - relevant `incident_details` fields via `merge_incident_detail_fields()`
  - `incident.note` by appending the newer khabar text
  - and it records `incident_updates.action='pipeline_merge'`
  (`app/news/repositories/incident_repository.py:586-641`, `app/news/services/incident_detail_merge.py:26-42`).

### Does a Day-3 follow-up automatically update casualty or asset numbers today?

- Yes, but only on the incident-level dedup merge path described above.
- No, on the fast-path duplicate-link path alone.
- No, if the row never gets an embedding before the relevant dedup check, because full materialization only attempts merge when `khabar_embedding is not None` (`app/news/services/incident_materialization_service.py:407-455`).
- No, if the dedup score stays below `0.80`; then the system either inserts a separate incident with `duplicate_flag=true` when score >= `0.50`, or inserts a normal new incident when lower (`app/news/services/incident_materialization_service.py:442-496`).

### Does `tier2_detail_fill` only run once per incident?

- In practice it runs until `details_pending` becomes `false`.
- The guard is explicit in the claim query and the incident lookup query (`app/news/repositories/pipeline_claim_repository.py:175-183`, `app/news/services/tier2_detail_fill_service.py:76-86`).
- I found no code that resets `details_pending` from `false` back to `true` when a later follow-up message arrives. New information arriving on another raw message does not reopen the original incident for Tier 2.
- So after the first successful Tier 2 fill, the original incident will not re-enter this stage unless some external/manual code changes `details_pending` again.

### What `incident_updates` captures today

- `pipeline_merge` is written when `merge_existing()` changes merge-tracked fields on an already-existing incident (`app/news/repositories/incident_repository.py:633-641`; enum added in `alembic/migration/20260819_0026_add_pipeline_merge_update_action.py:19`).
- That means a casualty-count update from a later follow-up **can** produce `pipeline_merge`, but only if the follow-up reaches the incident-level dedup merge path.
- Embedding/clustering-driven soft deletions and duplicate links use `duplicate_matches`; they do not themselves create `pipeline_merge` rows (`app/news/services/pipeline_sweep_stages.py:522-585`, `app/news/services/duplicate_match_reconciliation.py:53-87`).

### Plain statement of the gap

- There is **not** a universal automated path that updates an existing incident from every later follow-up message.
- Specifically, a later follow-up that gets short-circuited as a fast-path duplicate only creates a duplicate link record and does not merge casualty/asset counts into the existing incident row.
- Also, once an incident’s initial `details_pending` fill has completed, later incoming evidence does not reset it for re-fill.

## 5. Incidents page read-path recon

### Backend route and query shape

- The frontend uses `GET /api/incidents` (`app/api/incidents_router.py:24`, list route at `:39-63`; client call `frontend/src/features/news/api.ts:18-60`).
- Default pagination is hardcoded `limit=150`, `offset=0` in the router (`app/api/incidents_router.py:41-42`), and the page component also hardcodes `PAGE_SIZE = 150` (`frontend/src/features/news/pages/IncidentsPage.tsx:25`).
- Pagination is OFFSET-based, not cursor-based:
  - backend `.limit(params.limit).offset(params.offset)` (`app/news/repositories/incident_repository.py:124-128`)
  - frontend computes `offset = (page - 1) * PAGE_SIZE` (`frontend/src/features/news/pages/IncidentsPage.tsx:72`).
- Query shape is RawMessage-first with `LEFT OUTER JOIN incidents` and then left joins to `villages`, `conditions`, and `sources` (`app/news/repositories/incident_repository.py:65-119`).
- It is column-limited, not full-row ORM hydration. The select list is explicit labels like `Incident.id.label("id")`, `RawMessage.id.label("raw_message_id")`, `village`, `condition`, `khabar`, `source`, flags, timestamps, and version fields (`app/news/repositories/incident_repository.py:66-108`).

### Serialization / N+1

- I did not find an N+1 loop in the incidents list serialization. The list query already joins `Village`, `Condition`, and `Source`, and the response builds DTOs directly from result rows (`app/news/repositories/incident_repository.py:121-176`).
- The detail page path is separate and does join `IncidentDetail`, but that is not part of the list endpoint (`app/news/repositories/incident_repository.py:179-239`).

### Filters and index coverage

- List filters are built in `_list_filters()` and include village, condition, source type, event date range, `flagged_only`, `verification_status`, and `duplicate_only` (`app/news/repositories/incident_repository.py:781-828`).
- Ordering is by derived `created_at` / event date / event time (`app/news/repositories/incident_repository.py:831-846`).
- Existing relevant indexes I found:
  - `ix_raw_messages_source_platform` and `ix_raw_messages_source_name` (`alembic/migration/20260811_0005_add_raw_message_source_platform_name.py:29-34`)
  - trigram indexes on village/condition reference data used by matching, not by the incidents list endpoint: `ix_villages_acs_name_trgm`, `ix_villages_ref_name_ar_trgm`, `ix_conditions_action_ar_trgm` (`alembic/migration/20260811_0006_add_villages_conditions.py:75-83`)
  - `uq_incidents_exact_hash_active` (`alembic/migration/20260811_0007_add_incidents_incident_details.py:98-103`)
  - vector indexes for duplicate detection, not list-page filtering: `ix_incidents_khabar_embedding_hnsw`, `ix_raw_messages_content_embedding_hnsw` (`alembic/migration/20260811_0009_add_duplicate_detection.py:49-53`, `alembic/migration/20260814_0018_add_raw_message_duplicate_clustering.py:30-38`)
  - `ix_raw_messages_duplicate_of_id` and `ix_raw_messages_processing_claim_stage` (`alembic/migration/20260814_0018_add_raw_message_duplicate_clustering.py:47-58`, `alembic/migration/20260827_0036_add_raw_message_processing_claims.py:32-35`)
- Likely gaps for the current incidents list query:
  - no index visible here for `Incident.is_deleted`
  - no index visible for `Incident.event_date`
  - no index visible for `Incident.duplicate_flag`
  - no index visible for `RawMessage.status`
  - no index visible for the list sort expression based on `coalesce(Incident.created_at, RawMessage.received_at)`
  - no index visible for `Source.type`, which is used for the `source_type` filter (`app/news/repositories/incident_repository.py:810`)
- Because the query is RawMessage-first and conditionally incident-scoped only when some filters are present, the “best” index set depends on how often the default unfiltered list is used versus incident-only filtered searches.

### Client-side refetch / waterfall behavior

- `useIncidentsQuery(filters)` uses `liveListQueryOptions` with:
  - `refetchInterval = 30_000`
  - `refetchOnReconnect = true`
  - `refetchOnWindowFocus = true`
  - `staleTime = 0`
  (`frontend/src/features/news/hooks.ts:28-32`, `frontend/src/lib/liveListPolling.ts:2-9`).
- `IncidentsPage` fires three incidents-list queries at once:
  - main list query for the current page
  - `verificationSummary` with `limit=1`
  - `duplicateSummary` with `limit=1`
  (`frontend/src/features/news/pages/IncidentsPage.tsx:115`, `:125-148`).
- It also fetches villages and conditions in parallel (`frontend/src/features/news/pages/IncidentsPage.tsx:116-124`), though those are cached for 5 minutes on the client and 1 hour on the backend (`frontend/src/features/news/hooks.ts:12-24`, `app/api/conditions_router.py:13-40`, `app/api/villages_router.py:14-60`).
- So the page is not suffering from classic sequential waterfalls, but it does intentionally multiply backend load by issuing two extra polling list queries for summary counts.

## 6. Open questions / gaps found

- I could not verify real stage timings from the DB on 2026-09-02 because the configured host is `db` from Docker Compose and is not reachable from this shell environment, so no trustworthy read-only sampling was possible.
- The code records stage elapsed time in memory for sweep responses, but I did not find a persisted pipeline timing table or a log-ingestion path that would let us query “last few hundred stage runs” after the fact (`app/news/dtos/pipeline_dto.py:4-18`).
- Local relevance uses an inline prompt constant, and general extraction uses an inline prompt constant; only presence-gate and category-detail prompts live in files. Any optimization work that assumes “all prompts have file paths” will be wrong (`app/llm/services/local_llm_relevance_classifier.py:24-55`, `app/llm/services/ollama_extraction_service.py:31-94`, `app/llm/services/ollama_presence_gate_service.py:85-91`, `app/llm/services/ollama_category_detail_service.py:22-28`).
- There is no code path resetting `Incident.details_pending` back to `true` after a later follow-up message enriches the same real-world incident.
- Fast-path duplicate linking does not merge into the canonical incident. If the product expectation is “every follow-up should update the existing row,” that gap is real today.
- The incidents list endpoint issues a separate `COUNT(*)` and a separate `MAX(...)` query in addition to the page query (`app/news/repositories/incident_repository.py:121-176`), which is worth measuring during optimization work even though it is not a functional bug.
