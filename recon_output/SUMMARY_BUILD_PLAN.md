# Summary Bulletin Reconciliation — build plan

## Scope and conclusions

This is a read-only build plan. No application, frontend, test, or migration file was changed. The proposed feature belongs under `app/news/services/summaries/`: summaries operate on news-domain `RawMessage`, `Incident`, `AirViolation`, village, condition, and pipeline types, while the concern-subpackage convention keeps it out of the already crowded flat `services/` namespace (`scripts/check_stale_service_imports.py:24-76`).

Final worktree check: `git status --short` also reports pre-existing user changes to `frontend/src/features/news/components/VillageMatchNotice.test.tsx`, `frontend/src/features/news/pages/IncidentDetailPage.tsx`, and untracked `report.md`. This recon did not touch them. Recon-created files are confined to `scripts/recon/` (gitignored) and `recon_output/`; consequently the repository was already not clean and cannot truthfully satisfy a literal “only recon files in git status” assertion.

The existing `bulletin_reconciliation` worker is not this feature. It closes casualty-group lifecycle records (`app/news/services/reconciliation/bulletin_reconciliation_service.py:1-154`) and is useful only as the smallest periodic-worker template.

Defaults retained from the brief: D1 between X/Y is one item anchored on X with Y secondary; D2 repeated X and `اطراف X` collapse within one section/action; D3 `(N)` is an item count and mismatch is a note; D4 unmapped headers remain unknown and yield one group review; D7 settle after 60 minutes plus empty in-window backlog, force after four hours.

## 1. Codebase map

### 1.1 Domain conventions

1. `app/` is organized into `accounts`, `api`, `core`, `export`, `llm`, `logs`, `news`, and `sources`. A complete news slice has SQLAlchemy models in `app/news/models/` (for example `incident.py:50-204`), Pydantic DTOs in `app/news/dtos/` (`pipeline_dto.py:4-23`), repository interfaces in `app/news/interfaces/`, implementations in `app/news/repositories/`, orchestration actions in `app/news/actions/`, concern-specific services in `app/news/services/{pipeline,dedup,matching,materialization,...}/`, and HTTP routers in `app/api/`. Routers obtain a DB/auth dependency, instantiate repository → service/action, and return DTO/schema models; `app/api/incidents_router.py:35-79` is the representative composition root and `app/api/router.py:1-40` registers it. Dependency direction is API/actions → services → repository interfaces/DTOs/models, with concrete repositories wired at the API or pipeline composition boundary.

2. `scripts/check_stale_service_imports.py:21-22` scans Python under `app`, `tests`, `scripts`, and `alembic`; lines 24-72 enumerate modules moved from flat `app.news.services.*`; lines 74-76 reject imports using those stale flat paths. New imports must use `app.news.services.summaries.<module>`, never `app.news.services.<module>`. Use `app/news/services/summaries/`, not a new top-level `app/summaries/`, because all owned entities and sinks are news-domain and this follows existing concern packages.

3. Settings are typed lowercase fields on the singleton `Settings(BaseSettings)` (`app/core/config.py:5-6,199-223`), read from uppercase environment names by pydantic-settings. Add `summary_enabled: bool = False`, `summary_shadow_mode: bool = True`, `summary_llm_model: str = ...`, `summary_llm_num_ctx: int | None = None`, `summary_settle_minutes: int = 60`, `summary_force_settle_hours: int = 4`, and a sweep interval/batch cap beside the existing bulletin/pipeline settings (`app/core/config.py:160-180`). Consumers import `settings` and read once per operation, not environment variables directly.

4. The common batch result is immutable `StageSweepResult(stage, processed, succeeded, failed, aborted, abort_reason, unprocessed, elapsed_seconds)` (`app/news/dtos/pipeline_dto.py:4-14`), nested in `PipelineSweepResult` (`:17-23`). Sweep stages construct it (for example `pipeline_sweep_stages.py:734-757`); the orchestrator records and logs each result (`pipeline_orchestrator.py:195-207,348-379`). Summary sweep should return this type.

### 1.2 Pipeline and workers

5. The main worker is `python -m app.core.scripts.run_pipeline_worker`; it repeatedly calls the orchestrator, which runs relevance → dedup → embedding → Tier 1 → matching → fast path → Tier 2 → clustering/reconciliation (`pipeline_orchestrator.py:229-343`). `pipeline_jobs.py:110-156` coalesces queued requests with `FOR UPDATE SKIP LOCKED`; `pipeline_claim_repository.py:38-149` leases raw rows, and the worker/orchestrator reclaim stale process locks in `pipeline_advisory_lock.py:41-136`. Docker starts independent polling services in `docker-compose.yml`; the smallest feature-specific template is `bulletin-reconciliation-worker`, which invokes the casualty reconciliation service on an interval. Add an analogous `summary-reconciliation-worker` command/module, but use DB leasing/advisory locks rather than assuming one container forever.

6. `MessageStatus` values are `pending`, `parsed`, `materialized`, `duplicate`, `rejected`, `error`, `routed_air_violation`, and `held_for_review` (`app/news/models/raw_message.py:25-35`). Normal flow is ingestion → pending (`receive_cnrs_webhook_action.py:98`), relevance accept → parsed / reject → rejected (`relevance_filter_service.py:15-28`, `raw_message_repository.py:192-194`), extraction and matching remain parsed while filling stage payloads (`raw_message_repository.py:200-211`), materialization → materialized (`incident_materialization_service.py:1073`), pre/fast dedup → duplicate (`pre_extraction_dedup.py:191-195`, `incident_materialization_service.py:776`), air routing → routed_air_violation (`incident_materialization_service.py:954`), ambiguity → held_for_review (`:990`), and exceptions → error with `failed_stage` (`raw_message_repository.py:259-291,427-485`). Retry paths restore pending for relevance errors and parsed for extraction/matching errors (`:380-404,305-354,449-485`).

7. Hook A should be a new deterministic sweep immediately after relevance and before pre-extraction dedup/Tier 1. The current handoff to extraction is the orchestrator call at `pipeline_orchestrator.py:282-288`; extraction workers claim parsed rows without extraction at `pipeline_claim_repository.py:85-99` and call `ExtractIncidentsAction.execute` (`app/llm/actions/extract_incidents_action.py:105-144`). Insert `summary_detection` after relevance and before `dedup_original_reconciliation`. It claims `status=parsed AND extraction_result IS NULL`, runs `detect_summary`, creates/joins summary records, then sets `raw_messages.status='summary'`. This preserves relevance telemetry, prevents all later parsed-only stages from claiming it, and lets grouping supersede generic pre-dedup. Add the enum/database value, include it among terminal statuses in pipeline health (`pipeline_health_service.py:57-64`) and air-routing terminal statuses (`air_violation_routing.py:20`), expose it in All News status rendering, and audit any exhaustive frontend raw-status union. Parsed-only queries need no change because exclusion is desired; retry/rejected routes must refuse summary rows unless explicitly resolving a summary.

8. Current pre-extraction dedup compares normalized raw text with PostgreSQL `word_similarity`, within configured lookback/candidate narrowing (`pre_extraction_dedup.py:96-168`; `config.py:94-108`), then sets `duplicate_of_id` and status duplicate (`pre_extraction_dedup.py:191-195`). It can identify near-identical reposts, but it is unsuitable as group identity: wording/time/footer changes miss pairs, and `duplicate_of_id` is a single representative chain rather than a period/action union. Summary grouping needs its own normalized coverage fingerprint plus overlapping resolved window; it may record `duplicate_of_id` as ancillary provenance but must not depend on it.

9. Fast materialization starts at `IncidentMaterializationService.process_fast_path` (`incident_materialization_service.py:314`), builds per-village/action units (`:398-445`), and asks `FastPathDedupService.decide_for_village` whether to create/merge (`:447-456`). `_merge_into_canonical` is at `:819`; `_insert_fast_incident` at `:1109`; full-path construction occurs around `:1531`. The late-news hook belongs after acquiring the common creation lock and before ordinary fast-dedup decision: query active `origin='summary'` incidents by village, compatible condition, and summary window/date; merge through `_merge_into_canonical`/`IncidentMergeService` and upgrade exact event time/details/casualties. The ultimate “create versus merge” decision remains `decide_for_village`; extend its candidate source or introduce a preceding `find_summary_created_candidate` whose positive result is forced into the existing merge path.

10. A transaction advisory lock already protects `(village_id, condition_id)` during fast check/insert (`pipeline_advisory_lock.py:15-29`; acquired at materialization `:440-445`). It does not protect `(village_id, date)` across distinct conditions or the summary worker. Add `acquire_incident_day_lock(db, village_id, event_date)` using a stable 64-bit hash/key namespace. Both summary reconciliation and live materialization must acquire it before tombstone lookup, candidate lookup, refinement, merge, or insert. Keep the narrower existing lock temporarily for compatibility, with a documented consistent order: day lock then condition lock. The active exact-hash uniqueness constraint protects identical active rows, not the required day-level race (`incident_materialization_service.py:179`).

### 1.3 Reuse inventory

11. Village normalization is `normalize_arabic_text`/`village_match_key` (`app/core/text_normalization.py`); descriptor removal is `_strip_generic_descriptors` in `matching_service.py` (used by recon at `analyze_bulletin_structure.py:245-251`). `VillageRepository` queries `acs_name`/`ref_name_ar` and trigram candidates (`village_repository.py:140-190`); active approved aliases are modeled with normalized uniqueness (`village_location_alias.py:17-39`) and used by `VillageMatchingService`. Existing matchers are fuzzy and have no first-class caza filter; summary parsing needs a new exact-only gazetteer loader accepting `allowed_cazas` and returning ambiguity rather than picking the first ID. Distinct DB values are: Akkar; Aley; Baabda; Baalbek; Batroun; Bcharre; Beirut; Bint Jubail; Chouf; El Metn; Hasbaiya; Hermel; Jezzine; Jubail; Kasrouane; Koura; Marjaayoun; Minieh-Danieh; Nabatiye; Rachiaya; Saida; Sour; Tripoli; West Bekaa; Zahle; Zgharta. Default southern caza allowlist: **Bint Jubail, Hasbaiya, Jezzine, Marjaayoun, Nabatiye, Saida, Sour**. Spellings must match DB values exactly; do not reuse the broader air-violation “south” list (`air_violation_conditions.py:15-28`).

12. English condition text resolution is exact normalized lookup in `ConditionResolutionService.resolve` (`condition_resolution_service.py:6-15`); deterministic Arabic fallbacks/aliases live in `matching/condition_aliases.py` and `condition_evidence_override.py`. Conditions themselves have unique `action_ar` (`models/condition.py:10-24`). There is no persisted family/group concept. Add a summary header dictionary with exact normalized header → condition and a separate reviewed compatibility table/config; do not infer compatibility from fuzzy scores. Generic 46 and 87 may refine to specific kinetic conditions, while distinct specific actions remain separate.

13. `OllamaChatClient` fixes model in its constructor (`ollama_client.py:45-75`), accepts only response format and temperature per call (`:77-117`), and applies global `ollama_num_ctx`, not a per-call value (`:22-42`). `_content_from_payload` returns only message content (`:179-188`); `done_reason` and `prompt_eval_count` are discarded. Either instantiate a dedicated summary client with summary model and temporarily extend runtime options to accept explicit `num_ctx`, or preferably add an `OllamaChatResult(content, done_reason, prompt_eval_count)` detailed method while keeping existing `chat()` compatibility. No LLM was called during recon.

14. `app/core/llm_knowledge/index.yaml:1-93` registers named stages and their core/situational rules, few-shot sources, and terminology. `loader.py:159-221` loads YAML/Markdown/JSONL with caches; `PromptBuilder` begins at `:248`; `prompt_assembly.py:8-25` builds a stage prompt and rejects empty output. Register `summary_crosscheck` with `rules/summary_crosscheck_prompt.md`, `fewshot/summary_crosscheck_examples.jsonl`, and `terminology/summary_headers.yaml`; update `CHANGELOG.md` and integrity tests.

15. Existing summary-ish behavior: keep `sectioned_bulletin.py` for non-summary messages but bypass it after S0 diversion (`ollama_extraction_service.py:52`); bypass `_collapse_fuzzy_area_locations` for summaries and delete only after telemetry proves no other callers need it (`ollama_extraction_service.py:609-635,1732`); keep `is_multi_village_candidate` for ordinary Tier 1 but summaries never reach its fuzzy-area early false rule (`llm_knowledge/loader.py:40-78`); keep current flare/strike quality policy for ordinary incidents (`verification_signals.py:353`), while summary headers resolve deterministically; `_extraction_review_reason` (`incident_materialization_service.py:161-176`) remains for live extraction but is not applied message-wide to summary items.

16. Relevant incident columns are `raw_message_id`, village/condition/source IDs, `event_date`, nullable `event_time`, `khabar`, `story_group_id`, `note`, source links, casualty values/status, `quality_flags`, `note_extra`, exact/incident keys, duplicate state, `is_deleted/deleted_reason`, verification fields, and timestamps (`incident.py:65-180`). `casualty_updated_at` is on incident detail/update paths rather than the shown base model and must be preserved by the merge service. No existing field expresses summary origin or time precision. Add explicit `origin`, `time_precision`, and nullable `summary_group_id`; do not overload `note_extra` or `quality_flags`.

17. Air conditions are exactly 35, 36, 38 (`air_violation_conditions.py:7-14`). The model is `app/news/models/air_violation.py`; creation/routing is repository/service based (`air_violation_service.py:25-45`, `air_violation_repository.py:206+`) and normal raw-message routing occurs from `MatchIncidentAction` (`match_incident_action.py:95-135`). Window grouping and its surveillance duration are in `air_violations/window_grouping_service.py:38-44`. Summary air items should call a new repository lookup/reconcile method keyed by condition, window, and `AirViolationLocation.village_id`; match existing one-village-per-window/location association, create only through the air-violation service, and link via polymorphic summary item links.

18. `alembic heads` and `alembic current` both report `20261005_0075`; the historical graph contains duplicate numbered filenames/revisions, including the known `20260811_0004` lineage and multiple later same-number branches, merged by files such as `20260903_0049` and `20260928_0068`. Follow the current descriptive timestamp/sequence naming convention, e.g. `20261007_0076_add_summary_reconciliation.py`, with `down_revision='20261005_0075'`; verify `alembic heads` stays singular. Do not write the migration in recon.

### 1.4 API and frontend

19. `incidents_router.py` demonstrates route → concrete repository/service → DTO response (`:35-79`), registered under `/api` by `api/router.py`. Add `app/api/summaries_router.py` with `GET /summaries`, `GET /summaries/{group_id}`, and `POST /summaries/{group_id}/resolve`; wire it in `router.py`. Read endpoints may allow admin and super-admin; resolution must use the existing role dependency in `api/deps.py` and permit both `admin` and `super_admin`, recording user/time/audit entry. Keep business rules in a summary action/service, not the router.

20. Frontend feature boundaries are `frontend/src/features/<feature>/{api,hooks,types,pages,components}`. Routes are declared for both role trees in `src/app/routes.tsx:102-142`. This checkout has no `frontend/src/mocks/`; mock-first behavior should therefore follow existing API contract test/mocking utilities rather than inventing a dead directory. Queries use TanStack hooks in `features/news/hooks.ts`; shared `StatusBadge`, generic `DataTable`, and `formatRelativeTime` are at `src/components/StatusBadge.tsx`, `src/components/ui/DataTable.tsx`, and `src/lib/formatters.ts:31`. Create `features/summaries/` with list/detail API, types, hooks, pages, and review components. Add origin/confirmation badges to `IncidentBulletinRow.tsx:64-66`, `IncidentsPage.tsx:287-367`, and `IncidentDetailPage.tsx:230-262`, driven by DTO fields rather than parsing note text.

21. The Incidents verification tab is derived from `verification_status` and reason/open flags (`verificationLogic.ts:14`; `verificationReasons.tsx:138-143,216`), while bulletin grouping/counts are already surfaced (`IncidentsPage.tsx:229-236,420-483`). Do not create N incident verification rows. Represent one unresolved summary group in the summaries query/page and add one aggregated reason chip/link: “Daily summary: N items need a decision.” If product requires it in the Incidents tab, extend the response with summary review groups and count them as bulletin groups, not `Incident` objects; keep incident `verification_status` unchanged until a resolution actually affects an incident.

### 1.5 Tests

22. Tests are mostly flat `tests/test_*.py`, with focused `tests/news/`, `tests/eval_corpus/`, shared fakes (`tests/split_phase_fakes.py`), and JSON fixtures under `tests/fixtures/`. Pure tests instantiate dataclasses/Pydantic DTOs and pass fakes without a Session; repository/integration tests use the existing DB fixtures. Put golden cases in `tests/fixtures/summaries/*.json`; pure detector/window/parser tests in `tests/test_summary_{detector,window,parser}.py`; repository/settlement/reconciliation/late-merge/API tests in corresponding files. Parser/window modules must import neither SQLAlchemy nor application settings.

## 2. Corpus findings

Full output is in `recon_output/build_checks.md` and CSVs. Of 221 bulletins: 103 have an explicit date, 17 overnight-until wording, 2 detected incremental wording, and 99 fall into default/unknown wording. There are 45 channel-days with multiple corpus rows, validating the need for per-channel predecessor tracking, but exact-time duplicate repost rows mean predecessor selection must ignore same-group bulletins and require strictly earlier posting time.

For the first 20 fully gazetteer-resolved parses, the heuristic produced 423 items: 223 exact-condition village matches (52.7%), 92 no-village-window matches (21.7%, would create), and 108 village matches with different conditions (25.5%). The crosstab is dominated by 46↔specific-action collisions; compatibility cannot be “same village means match.” Exact actions match cleanly (e.g. 21→21: 85; 5→5: 225), while 21→46 (88) and 5→46 (60) support generic-to-specific refinement. Cross-specific pairs should stay distinct.

The clean set resolved mostly to Bint Jubail, Hasbaiya, Marjaayoun, Nabatiye, and Sour. One Jubail and three West Bekaa resolutions are outside the proposed list and must become unresolved/review, not silently accepted. The generated report incorrectly labels Bint Jubail as non-southern because the recon script's display set used a spelling variant; production must use the exact DB value `Bint Jubail`.

The raw late-news query found 4,626 rows across 192/221 bulletins, but it is an upper bound: it counts every same-village/day incident created after posting, including delayed ingestion/reprocessing and repeated bulletin coverage. It strongly justifies the hook, but it must not be used as an expected merge rate without event-time/condition/group deduplication.

Window impact: the corpus contains wording such as “من منتصف الليل حتى الساعة” with no usable time, so default 00:00→posting is correct. The current simple frequency regex undercounts semantic “until now” variants after Arabic normalization; production detector tests must cover `إلى/الى`, `حتى/حتي`, and “منتصف الليل” separately. Explicit dates must construct local-midnight boundaries with `ZoneInfo('Asia/Beirut')`, never fixed UTC offsets, to survive late-October DST.

## 3. Proposed file tree

```text
app/news/models/summary_group.py                 group/window/status/settlement metadata
app/news/models/summary_bulletin.py              raw-message membership and reporting channel
app/news/models/summary_item.py                  immutable parsed action/place/evidence/item key
app/news/models/summary_item_link.py             item → incident/air-violation outcome/audit link
app/news/models/header_dictionary.py             approved normalized header mapping
app/news/dtos/summary_dto.py                      internal and API contracts
app/news/interfaces/summary_repository_interface.py persistence boundary
app/news/repositories/summary_repository.py       claims, grouping, links, tombstones, candidates
app/news/services/summaries/detection.py          pure S0 detector
app/news/services/summaries/window.py             pure Beirut-aware S2 resolver
app/news/services/summaries/gazetteer.py          exact southern village snapshot builder
app/news/services/summaries/parser.py             pure deterministic S3 parser
app/news/services/summaries/condition_compatibility.py pure compatibility/refinement policy
app/news/services/summaries/crosscheck.py          constrained S4 adapter/validator
app/news/services/summaries/grouping_service.py    S1 membership and item union
app/news/services/summaries/settlement_service.py  S5 eligibility/backlog policy
app/news/services/summaries/reconciliation_service.py S6 transaction and outcomes
app/news/services/summaries/late_live_merge.py      lookup/merge of summary-created incidents
app/news/services/summaries/worker.py               polling, leases, batch result
app/news/actions/list_summaries_action.py            list/detail application use cases
app/news/actions/resolve_summary_review_action.py     validated admin resolution
app/api/summaries_router.py                          HTTP endpoints and auth wiring
app/core/scripts/run_summary_reconciliation_worker.py worker entry point
app/core/llm_knowledge/rules/summary_crosscheck_prompt.md constrained cross-check rules
app/core/llm_knowledge/fewshot/summary_crosscheck_examples.jsonl evidence-bound examples
app/core/llm_knowledge/terminology/summary_headers.yaml header terminology
alembic/migration/20261007_0076_add_summary_reconciliation.py schema only (future build)
tests/fixtures/summaries/*.json                      golden input/expected parse/window
tests/test_summary_detector.py                       pure S0 tests
tests/test_summary_window.py                         pure DST/predecessor tests
tests/test_summary_parser.py                         pure golden/coverage tests
tests/test_summary_grouping_service.py               repost union/idempotency
tests/test_summary_settlement_service.py             grace/backlog/force rules
tests/test_summary_reconciliation_service.py         match/refine/create/tombstone/air/review
tests/test_summary_late_live_merge.py                 late merge and lock races
tests/test_summaries_api.py                           auth/list/detail/resolve contracts
frontend/src/features/summaries/types.ts              API types
frontend/src/features/summaries/api.ts                request functions
frontend/src/features/summaries/hooks.ts              TanStack queries/mutations
frontend/src/features/summaries/pages/SummariesPage.tsx list and Done/review filters
frontend/src/features/summaries/pages/SummaryDetailPage.tsx item evidence/outcomes
frontend/src/features/summaries/components/SummaryReviewPanel.tsx one group decision UI
frontend/src/features/summaries/*.test.tsx             presentation and contract tests
```

## 4. Module contracts

- `detect_summary(text: str) -> SummaryDetection` — pure; returns `is_summary`, marker hits, header count, location-segment count, confidence/reasons. Marker match OR the ≥2-header/≥6-segment structural rule is sufficient.
- `resolve_window(text: str, posted_at: datetime, previous_summary_end: datetime | None) -> SummaryWindow` — pure; aware Beirut start/end plus rule/evidence. Reject naive `posted_at` or normalize it explicitly.
- `build_summary_gazetteer(db: Session, allowed_cazas: frozenset[str]) -> GazetteerSnapshot` — DB read; exact `ref_name_ar`, `acs_name`, active approved aliases; ambiguity retained.
- `parse_summary(text: str, gazetteer: GazetteerSnapshot, header_dict: HeaderDictionarySnapshot) -> ParseResult` — pure; returns ordered `ParsedSummaryItem`s, headers, `leftover_tokens`, unresolved headers/places, count notes, and `auto_acceptable = not leftovers/unresolved/ambiguity`.
- `crosscheck_summary(text: str, parsed: ParseResult) -> CrosscheckResult` — LLM call; suggestions only. `validate_crosscheck(result, text, gazetteer) -> ValidatedCrosscheck` is pure and enforces verbatim evidence/exact village/no deletion.
- `group_bulletin(db, raw_message_id, detection, window, parse) -> UUID` — DB write; idempotently selects/creates group, adds bulletin/channel, unions items by stable key.
- `settlement_decision(group, now, active_backlog_count) -> SettlementDecision` — pure; eligible after end+60m and zero backlog, forced after end+4h.
- `claim_settleable_groups(db, limit, worker_id) -> list[UUID]` — DB write/lease with `FOR UPDATE SKIP LOCKED`.
- `reconcile_group(group_id: UUID) -> ReconcileReport` — DB touching; one transaction, group advisory lock, deterministic item order/day locks, outcomes `{matched, refined, created, skipped_tombstone, review}` and counts.
- `find_summary_created_candidate(db, village_id, condition_id, event_at) -> Incident | None` — DB read under day lock; used by live materialization.
- DTOs: `SummaryDetection`, `SummaryWindow`, `ParsedSummaryItem(primary_village_id, secondary_village_id, condition_id, qualifier, count, evidence_span, item_key)`, `ParseResult`, `CrosscheckProposal`, `SummaryGroupDTO`, `SummaryItemDTO`, `SummaryReviewResolution`, `ReconcileReport`.

## 5. Minimal hooks and risks

1. `pipeline_orchestrator.run_pipeline_sweep` (`pipeline_orchestrator.py:229-269`): add summary detection after relevance. Risk: claiming overlaps with pre-dedup; mitigate with the existing claim repository and stage lease.
2. `MessageStatus` (`raw_message.py:25-35`) plus enum migration: add `summary`. Risk: PostgreSQL enum deployment ordering; migrate before new code.
3. `pipeline_health_service.py:57-64,102-180`: treat summary as terminal for live stages and expose summary queue separately. Risk: false “stuck parsed” counts if omitted.
4. `IncidentMaterializationService.process_fast_path` around `:440-456`: acquire day lock and check late summary candidate before ordinary dedup. Mirror in full path around `:1531`. Risk: lock ordering/deadlock and accidental merging of different actions; compatibility table and deterministic lock order required.
5. Incident/API serializers around `_new_incident_payload` (`incident_materialization_service.py:186-252`) and incident DTO/router: add origin/time precision/summary confirmation fields. Risk: contract break; fields nullable/defaulted.
6. `app/api/router.py`: include summaries router. Frontend `routes.tsx:102-142`: add both role routes/navigation. Risk: role parity drift; route tests for both.
7. Ollama client detailed response/per-call context (`ollama_client.py:22-42,77-117,179`): backward-compatible overload/new method only. Risk: changing return type would break all LLM callers; do not change existing `chat()` return type.

## 6. Schema proposal

- `summary_groups`: UUID PK; `window_start/window_end timestamptz`; `timezone varchar(64)` default Asia/Beirut; `coverage_fingerprint char(64)`; status enum/check; `settle_after`, `force_after`, lease fields; `review_reason`; counts; created/updated/settled timestamps; optional resolver user/time. Unique `(coverage_fingerprint, window_start, window_end)` and indexes on `(status, settle_after)`.
- `summary_bulletins`: bigint PK; `summary_group_id` FK cascade; `raw_message_id` FK restrict unique; channel/account; posted_at; normalized_text_hash; detection/parse/crosscheck JSONB snapshots; created_at. Unique raw membership records every channel without duplicating items.
- `summary_items`: UUID PK; group FK cascade; stable `item_key`; condition FK nullable; primary village FK nullable; secondary village FK nullable; raw/normalized header and location; qualifier; reported_count; verbatim evidence span and offsets; parser/crosscheck provenance; resolution state/note; timestamps. Unique `(summary_group_id,item_key)`; check secondary differs from primary.
- `summary_item_links`: bigint PK; item FK cascade; nullable incident UUID FK and nullable air violation bigint FK; outcome; source (`parser/crosscheck/admin`); before/after JSONB; created_at/user. Check exactly one target for target-bearing outcomes; unique item/outcome/target prevents replay.
- `header_dictionary`: bigint PK; `normalized_header` unique; condition FK nullable; status (`approved/unknown/rejected`); notes; created/updated/resolved user/time. Unknown headers can aggregate review without becoming mappings.
- `incidents`: `origin varchar(16) NOT NULL DEFAULT 'live'` check live/summary/import; `time_precision varchar(16) NOT NULL DEFAULT 'exact'` check exact/window/unknown; nullable `summary_group_id` FK SET NULL/index. Confirmation is many-to-many through item links; do not encode all channels in one incident column.

Use project timestamp conventions (`DateTime(timezone=True)`, `func.now()`), PostgreSQL UUIDs, explicit named checks/uniques, and soft-delete awareness. Summary records are workflow/audit records and should not be soft-deleted; status Done preserves them.

## 7. State machine

`summary_groups.status`:

`collecting` → `parsed` when at least one bulletin parsed; `parsed` → `crosscheck_pending` only when configured/needed; → `awaiting_settlement`; → `reconciling` under lease/lock; → `done` if every item matched/refined/skipped safely; → `done_with_additions` if items were created; → `needs_review` for true ambiguity/unconsumed tokens/unknown header; transient failure → `retryable_error` → prior pending state; permanent/admin close → `closed`. Shadow mode performs all transitions and links proposed outcomes but never mutates incidents/air violations. Reposts may join collecting/awaiting groups; after reconciliation they add provenance and may trigger idempotent re-evaluation only for genuinely new item keys.

New raw status: `summary`, terminal for the live extraction pipeline and linked to one `summary_bulletins` row. It does not mean the group is done.

## 8. Reuse versus new

|Capability|Decision|
|---|---|
|Arabic normalization|Reuse `core/text_normalization.py`, add summary-specific digit/tatweel behavior in pure parser|
|Village data/aliases|Reuse tables/repository concepts; new exact-only southern snapshot|
|Descriptor vocabulary|Reuse terminology/strip rules; parser owns qualifier semantics|
|Condition lookup|Reuse conditions; new approved header dictionary and compatibility policy|
|Ollama transport|Reuse with backward-compatible detailed/per-call options extension|
|Knowledge loader|Reuse; register `summary_crosscheck`|
|Worker result/loop|Reuse `StageSweepResult` and periodic worker pattern|
|Claims/orphan safety|Reuse `FOR UPDATE SKIP LOCKED` conventions; new group lease|
|Creation lock|Extend existing advisory-lock module with village/day lock|
|Incident merge|Reuse canonical merge/audit services; add summary candidate lookup|
|Air violations|Reuse model/service/window grouping; new summary item lookup/link|
|Badges/table/time formatting|Reuse `StatusBadge`, `DataTable`, `formatRelativeTime`|
|Summary list/detail/review UI|New feature package|

## 9. Build order and gates

1. Pure detector, window resolver, DTOs, and golden fixtures. Gate: unit tests including Beirut DST boundaries and marker/structural false positives.
2. Pure parser/gazetteer snapshot contract/header fixtures. Gate: every golden location token consumed; D1-D4 tests; no SQLAlchemy imports in parser/window modules.
3. Migration/models/repository for summary tables and incident columns. Gate: upgrade/downgrade on disposable DB, singular Alembic head, constraints/idempotency tests.
4. Detection pipeline stage behind `SUMMARY_ENABLED=false`. Gate: existing pipeline tests plus summary rows never claimed by Tier 1 and health remains green.
5. Grouping/window predecessor logic. Gate: repost union, strict-earlier same-channel predecessor, same-time duplicates, DST tests.
6. Constrained cross-check behind separate model/context settings. Gate: mocked client only; verbatim evidence/exact place enforcement and “cannot remove parser item.”
7. Settlement worker in **shadow mode only**. Gate: grace/backlog/force/lease/orphan tests and `StageSweepResult` telemetry.
8. Shadow candidate reconciliation and admin API/UI. Gate: corpus comparison, one group-level review, role tests, frontend contract tests. Calibrate compatibility families from adjudicated crosstab.
9. Incident/air write reconciliation still feature-flagged. Gate: one-transaction rollback, tombstone, idempotency, concurrency, audit, and air-routing tests.
10. Late live merge hooks last. Gate: concurrent summary/live creation test, exact-time/casualty enrichment, different-action non-merge, admin-deleted tombstone.
11. Gradual enablement: shadow telemetry → selected channels → all channels; only then consider retiring summary-specific fallback behavior. Every step is separately committable.

## 10. Risks and open questions

- Group identity across differing windows/reposts needs an adjudicated tolerance; content fingerprint alone will split edited reposts, window overlap alone can merge distinct partial bulletins.
- “Previous summary end” must exclude reposts and same-timestamp duplicates and define whether explicit whole-day summaries reset incremental state.
- Condition compatibility needs product/domain approval. Corpus evidence supports only generic→specific refinement, not arbitrary symmetric families.
- Gazetteer ambiguity must never pick lowest ID; the outside-south examples show why strict caza filtering is mandatory.
- Tombstones require an explicit durable key. A soft-deleted incident alone may not preserve the summary item key unless links survive deletion.
- Air-violation “one village per window” terminology should be reconciled with the current multi-location association model before schema coding.
- Count `(N)` semantics can mean strikes rather than locations; retain as reported count/note until domain review.
- LLM cross-check cost/capacity and the actual larger model are deployment decisions; default model value should be explicit but disabled until measured.
- The late-news estimate is inflated by ingestion/reprocessing time and repeated bulletins; obtain an adjudicated sample before tuning merge windows.
- The current corpus parser misses inline/emoji header variants and the recon window classifier undercounts normalized wording. Build gates must use a curated golden set, not the reported clean-20 alone.
