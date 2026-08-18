# Pipeline Master Fix — Full Implementation Report

> **Date**: 2026-08-18  
> **Scope**: Tasks 0–6 of the War News 2026 pipeline fix plan, plus Task 4 v2 descriptor recon  
> **Status**: Implementation complete for Tasks 1, 3, 4 (v1), 5, 6; Task 4 v2 descriptor strip **pending confirmation**; Task 0 (CNRS trust skip) **not in this changeset**; Task 2 (backlog sweep) is a manual ops step.

---

## Executive summary

This changeset transforms the news pipeline from a set of manual CLI scripts into an orchestrated 7-stage automated sweep, cuts duplicate-processing cost at two layers (pre-extraction text dedup + widened clustering + incident-level dedup), supports multi-village bulletins end-to-end, and wires category-level extraction data through to `incident_details` with computed rollups.

**Git diff scale** (vs HEAD): **31 files modified**, **+1,181 / −608 lines**; **12 new files** untracked.

| Task | Description | Status |
|------|-------------|--------|
| **0** | Trust CNRS relevance verdict (skip Step A LLM) | **Not implemented** in this diff — `cnrs_classification` is stored on ingest but not consulted by `FilterRelevanceAction` |
| **1** | Pre-dedup pass before extraction | **Done** |
| **2** | Full backlog sweep | **Manual** — run once after deploy, via `POST /api/pipeline/sweep` or orchestrator |
| **3** | Widen clustering window + retune threshold | **Done** (config only) |
| **4 v1** | Multi-village extraction/matching | **Done** |
| **4 v2** | Descriptor-prefixed village names | **Recon done** — strip-list **awaiting your confirmation**; `word_similarity()` switch **not yet applied** |
| **5** | Wire `DedupMatchingService` into materialization | **Done** |
| **6** | Populate automated rollup fields + DID gating | **Done** |

---

## Pipeline architecture

### Stage order (after this changeset)

```
1. sweep_relevance_filter      ← Step A (LLM relevance)
2. sweep_pre_extraction_dedup  ← NEW (pg_trgm word_similarity, no LLM)
3. sweep_extraction            ← Step B (LLM extraction)
4. sweep_matching              ← Phase 3 (DB trigram match)
5. sweep_embedding_generation    ← Phase 4a
6. sweep_clustering              ← Phase 4b
7. sweep_materialization         ← Phase 5
```

**Trigger**: `POST /api/pipeline/sweep` (`app/api/pipeline_router.py`) runs `run_full_pipeline_sweep()` in a FastAPI background task. A PostgreSQL advisory lock (`84729103`) serializes concurrent sweeps.

**Eligible row filters per stage**:

| Stage | Selects rows where… |
|-------|---------------------|
| relevance_filter | `status=pending`, `filter_result IS NULL` |
| pre_extraction_dedup | `status=parsed`, `extraction_result IS NULL`, `duplicate_of_id IS NULL` |
| extraction | `status=parsed`, no extraction yet (via extract action) |
| matching | `status=parsed`, has extraction, no match_result (unless rematch) |
| embedding | `status=parsed`, `content_embedding IS NULL` |
| clustering | `status=parsed`, has embedding + match_result, not already duplicate |
| materialization | `status=parsed`, has match_result, not duplicate |

### Sweep log output

Each stage emits:

```
Pipeline stage=<name> processed=N succeeded=M failed=F elapsed_seconds=X.XX
```

Final summary lists all stages in order. The new stage appears as:

```
stage=pre_extraction_dedup processed=… succeeded=… failed=… elapsed=…
```

between `relevance_filter` and `extraction`.

---

## Task 1 — Pre-dedup pass before extraction

### What it does

Before any extraction LLM call, compares each relevance-passed message's `raw_text` against all non-rejected messages received in the **last 48 hours** using PostgreSQL `pg_trgm word_similarity()`. Near-verbatim copies are marked duplicate immediately.

### Decisions implemented

| Setting | Value |
|---------|-------|
| Method | `word_similarity()` in SQL — zero embedding/LLM cost |
| Comparison set | `status != 'rejected'`, `received_at >= NOW() - 48h` |
| Threshold | `pre_dedup_similarity_threshold = 0.92` (`config.py`) |
| On match | `status='duplicate'`, `duplicate_of_id=<best match id>`, skip extraction |
| Audit log | `pre_extraction_dedup raw_message_id=… word_similarity=0.XXX similar_to_raw_message_id=…` |

### Files

| File | Change |
|------|--------|
| `app/core/config.py` | Added `pre_dedup_similarity_threshold` |
| `app/news/services/pipeline_sweep_stages.py` | New `sweep_pre_extraction_dedup()` |
| `app/news/services/pipeline_orchestrator.py` | Wired between filter and extraction |
| `tests/test_pre_extraction_dedup.py` | **New** — match, no-match, out-of-window cases |

---

## Task 3 — Clustering window + similarity threshold

### What changed

Config-only update in `app/core/config.py`:

| Setting | Old | New |
|---------|-----|-----|
| `cluster_time_window_minutes` | 90 | **300** (5 hours) |
| `cluster_similarity_threshold` | 0.90 | **0.75** |
| `cluster_require_condition_match` | True | True (unchanged) |

Comment block documents these as **first-pass values** from a single confirmed duplicate pair (248 min gap, 0.7675 cosine similarity). Revisit after 2–3 weeks of live data.

### Tests affected

**None.** `test_clustering_service.py` and `test_run_clustering.py` pass explicit constructor args and do not read from `settings`.

---

## Task 4 v1 — Multi-village extraction and matching

### Data model changes

**Extraction** (`app/llm/dtos/extraction_dto.py`):

```python
village: list[str] | None = None  # was str | None
```

- Pydantic `field_validator(mode='before')` coerces legacy single strings and comma-separated values to lists.
- Extraction prompt updated to request a JSON array (see `GENERAL_EXTRACTION_PROMPT` in `ollama_extraction_service.py`).
- Backward-compatible parse: comma-separated model output → split into list.

**Matching** (`app/news/dtos/match_result_dto.py`):

```python
class VillageMatchResult(BaseModel):
    matched_village_id: int | None
    village_confidence: float | None
    village_match_status: MatchResultStatus
    village_review_required: bool
    raw_village_text: str | None          # original LLM phrase preserved

class MatchResultDTO(BaseModel):
    village_matches: list[VillageMatchResult]
    any_village_low_confidence: bool      # denormalised for JSONB queries
    matched_condition_id: int | None
    condition_confidence: float | None
    condition_match_status: MatchResultStatus
    condition_review_required: bool
    raw_condition_text: str | None
```

**Backward compatibility**: `_normalize_match_result()` in materialization and `village_ids_from_match_result()` in clustering accept both old flat shape and new list shape.

### Behavior

| Layer | Behavior |
|-------|----------|
| **MatchingService** | Loops over `extraction_result.village` list; one `VillageMatchResult` per entry |
| **Materialization** | Returns `list[Incident]` — one row per eligible village_match; skips unmatched villages without blocking others |
| **Clustering** | Candidate pairs share **any** `matched_village_id`; orphan rule below |
| **Frontend** | `IncidentsPage.tsx` shows shared-bulletin note when multiple rows share `raw_message_id` |

### Orphan handling (clustering)

When a multi-village message joins a cluster:

- **Fully subsumed** (all member villages covered by representative) → `duplicate_of_id` set; all incidents for that raw_message soft-deleted.
- **Partially subsumed** (only some villages overlap) → `soft_delete_for_village_incident(raw_message_id, village_id)` per shared village only; other village incidents stay active; `duplicate_of_id` **not** set.

New repository method: `IncidentRepository.soft_delete_for_village_incident()`.

### Judgment calls (documented)

1. **`any_village_low_confidence`** at top level avoids rewriting JSONB array-path SQL in `_low_confidence_match()`.
2. **`duplicate_of_id`** only when entire village set is subsumed — decided from match_result, not re-querying incidents table.
3. **Transitivity gap**: union-find can chain A↔B (village X) and B↔C (village Y) without A↔C sharing a village — no soft-delete for that pair (preserves data over false deletion).
4. **Air violation routing** uses first matched village from `village_matches`.

### Files

| File | Change |
|------|--------|
| `app/llm/dtos/extraction_dto.py` | `village` → list |
| `app/llm/services/ollama_extraction_service.py` | Prompt + schema + comma-split parse |
| `app/news/dtos/match_result_dto.py` | `VillageMatchResult` + list shape |
| `app/news/services/matching_service.py` | Multi-village loop |
| `app/news/services/incident_materialization_service.py` | Per-village incident loop |
| `app/news/services/clustering_service.py` | Multi-village ID overlap |
| `app/news/services/pipeline_sweep_stages.py` | Partial vs full subsumption in clustering |
| `app/news/repositories/incident_repository.py` | `soft_delete_for_village_incident`, `raw_message_id` in list query |
| `app/news/repositories/air_violation_repository.py` | Read first village from list |
| `frontend/src/features/news/types.ts` | `raw_message_id` on Incident |
| `frontend/src/features/news/pages/IncidentsPage.tsx` | Shared-bulletin indicator |
| `tests/test_extraction_service.py` | Comma-split, array parse |
| `tests/test_matching_service.py` | Multi-village match |
| `tests/test_incident_materialization_service.py` | Two-village → two incidents |
| `tests/test_clustering_service.py` | Multi-village overlap + orphan |

---

## Task 4 v2 — Descriptor-prefixed village names (PENDING)

### Problem

Extracted phrases like `حرش عيتا الجبل` include a geographic descriptor (`حرش` = grove of) that is not part of the registered village name (`عيتا الجبل الزط`). Whole-string `similarity()` matching scores ~0.3–0.4 and fails.

### v1 status vs v2 gaps

| v2 requirement | Status |
|----------------|--------|
| Switch village matching to `word_similarity()` | **Not done** — `VillageRepository.find_similar()` still uses `similarity()` |
| Descriptor strip-list from real data | **Recon done**, list **not coded** — awaiting confirmation |
| Preserve unstripped phrase on incident | **Partial** — `raw_village_text` on match result; **`note_extra` not yet written** on incident row |

### Descriptor recon (offline)

**Method**: `scripts/descriptor_recon.py` cross-referenced 3,084 village names from `Data/Villages.json` against 86 bulletin texts from phase-2 test corpus + known DB case. Live DB query was not available from dev environment (`host "db"` is Docker-internal).

**Proposed strip-list (pending your confirmation)**:

| Word | Safe to strip? | Evidence |
|------|----------------|----------|
| **حرش** | ✅ Yes | Known DB case; no village starts with `حرش` |
| **خراج** | ✅ Yes | `خراج إبل السقي` → matches `إبل السقي` |
| **اطراف** | ✅ Yes | Covers `أطراف` after normalization; `اطراف بلدة حداثا` → `حداثا` |

**Explicitly exclude** (registered villages start with these words):

| Word | Example registered names |
|------|--------------------------|
| **وادي** | `وادي جزين`, `وادي فعرا`, … (19 villages) |
| **مشاع** | `مشاع الفتوح`, `مشاع كفر ذبiyan`, … (4 villages) |
| **ضهر** | `ضهر ابي ياغي`, `ضهر المغارة`, … |
| **مزارع** | `مزارع شبعا` |

**Needs guard logic, not blind strip**: `محيط`, `مشاع` (descriptor vs village name collision), `بالقرب من` (multi-token), `جنوب`.

**Preservation plan**: write original phrase to `incidents.note_extra` when strip is applied (`note` is reserved for dedup-merge append).

Full recon output: `DESCRIPTOR_RECON.md`. Re-run against live DB: `PYTHONPATH=. python scripts/descriptor_recon.py`.

---

## Task 5 — DedupMatchingService wired into materialization

### What it does

Before creating a new incident, queries existing incidents (same village, ±3 days, embedding similarity) via `DedupMatchingService.find_best_match()`:

| Score | Action |
|-------|--------|
| ≥ `dedup_high_threshold` (0.80) | `merge_into_incident()` — no new row; `merged_into_existing` stat incremented |
| ≥ `dedup_low_threshold` (0.50) | Create incident with `duplicate_flag=True` |
| < 0.50 or no embedding | Create normally, `duplicate_flag=False` |

Runs **inside the per-village loop** (once per village-incident being created).

### Config (`app/core/config.py`)

```python
dedup_time_window_days: int = 3
dedup_high_threshold: float = 0.80
dedup_low_threshold: float = 0.50
```

`DedupMatchingService` reads from `settings`; module-level `DEDUP_HIGH_THRESHOLD` / `DEDUP_LOW_THRESHOLD` aliases preserved for backward-compatible imports.

### Duplicate flag field

Uses existing `incidents.duplicate_flag` (`Boolean NOT NULL DEFAULT false`) — **no migration required**. Visible on frontend flagged-incidents filter via `IncidentRepository._list_filters(flagged_only=True)`.

### Files

| File | Change |
|------|--------|
| `app/core/config.py` | Three dedup settings |
| `app/news/services/dedup_matching_service.py` | Read from config |
| `app/news/services/incident_materialization_service.py` | Dedup gate per village |
| `app/news/services/pipeline_sweep_stages.py` | Inject `DedupMatchingService` into materialization |
| `tests/test_incident_materialization_service.py` | High/mid/low/no-embedding dedup tests |

---

## Task 6 — Category mapping + automated rollups

### What it does

The LLM already extracts per-category detail into `ExtractionResult.categories` (presence gate + per-category LLM calls). Materialization previously ignored this and wrote only 6 root casualty sub-fields. Now:

1. **`map_categories()`** — maps each `ExtractionCategoryKey` → `incident_details` columns (flags, DID, sub-casualties, rollups).
2. **`compute_rollups()`** — computes `total_deaths` / `total_injuries` on `incidents` as sum of root + all category totals (replaces LLM-provided pre-summed totals).
3. **DID gating** — flag=True when category present; `*_did` set from LLM `did` value when flag is True.
4. **Ambiguous categories** — keyword match on `category.name` for school/university and religious/cultural; fallback to `other=True, other_type="*_unclassified"` when no confident match.

### Field mapping (implemented)

| ExtractionCategoryKey | Flag | DID | Name | Sub D/I cols | Total cols |
|---|---|---|---|---|---|
| `lebanese_army` | `la` | `la_did` | — | `lam_*`, `laf_*` | `la_td`, `la_ti` |
| `unifil` | `unifil` | `un_did` | — | `unm_*`, `unf_*` | `un_td`, `un_ti` |
| `municipality` | `muni` | `muni_did` | — | `munim_*`, `munif_*` | `muni_td`, `muni_ti` |
| `hospital` | `hosp` | `hos_did` | `hos_n` | `hosm_*`, `hosf_*` | `hosd`, `hosi` |
| `health_center` | `hc` | `hc_did` | — | `hcm_*`, `hcf_*` | `hcd`, `hci` |
| `press` | `press` | `press_did` | `channel` | `pressm_*`, `pressf_*` | `pressd`, `pressi` |
| `government_building` | `gov` | `gb_did` | `gov_n` | `gbm_*`, `gbf_*` | `gbd`, `gbi` |
| `vehicles` | `car` | — | — | `carm_*`, `carf_*` | `card`, `cari` |
| `emergency_civil_defense` | `emer` | — | — | — | `emer_d`, `emer_i` |
| `crossings_other` | `crossing` | — | — | — | — |
| `warning_classification` | `warning` / `no_warning` | — | — | — | — |
| `school_university` | `school` / `uni` | `sch_did` / `uni_did` | `school_name` / `uni_name` | — | — |
| `religious_cultural` | `church`/`mosque`/`ceme`/… | per-entity | per-entity names | — | — |
| `casualty_demographics` | (root) | — | — | `male_*`, `female_*`, `children_*` | — |

Global rollups:

```
total_deaths   = deaths + la_td + un_td + muni_td + hosd + hcd + pressd + gbd + card + emer_d
total_injuries = injuries + la_ti + un_ti + muni_ti + hosi + hci + pressi + gbi + cari + emer_i
```

Returns `None` when all inputs are null (no false zero).

### Files

| File | Change |
|------|--------|
| `app/news/services/category_mapper.py` | **New** — pure mapping + rollup functions |
| `app/news/services/incident_materialization_service.py` | Calls mapper; spreads `**mapped_fields` into `IncidentDetail` |
| `tests/test_category_mapper.py` | **New** — 12 pure-function tests |
| `tests/test_incident_materialization_service.py` | Rollup assertion updated; category pass-through test |

### Test assertion change (intentional)

`test_casualty_fields_map_from_top_level_extraction_result` now expects `total_deaths=3, total_injuries=7` (computed from root `deaths`/`injuries`) instead of `(8, 13)` from LLM's pre-summed `casualties.total_deaths/injuries`. This reflects the new rule: **never trust LLM-provided rollup totals**.

---

## Task 0 — CNRS trust skip (NOT in this changeset)

The master plan listed Task 0 as "already approved" — skip Step A LLM when CNRS's own `cnrs_classification` verdict is available (~90% of rows).

**Current state**: `cnrs_classification` JSONB is populated at webhook ingest (`receive_cnrs_webhook_action.py`) but **`FilterRelevanceAction` does not consult it** — every relevance-passed row still goes through keyword prefilter + LLM classifier unless keyword-rejected.

**Changes to `filter_relevance_action.py` in this diff**: per-item try/except on save only (error isolation), not CNRS trust logic.

---

## Configuration reference

All tunable thresholds in `app/core/config.py` (overridable via `.env`):

| Setting | Default | Purpose |
|---------|---------|---------|
| `cluster_time_window_minutes` | 300 | Phase 4 clustering time window |
| `cluster_similarity_threshold` | 0.75 | Phase 4 cosine similarity gate |
| `cluster_require_condition_match` | true | Phase 4 condition-ID gate |
| `pre_dedup_similarity_threshold` | 0.92 | Pre-extraction text dedup |
| `dedup_time_window_days` | 3 | Incident-level dedup lookback |
| `dedup_high_threshold` | 0.80 | Auto-merge into existing incident |
| `dedup_low_threshold` | 0.50 | Flag as possible duplicate |

---

## New files (untracked)

| File | Purpose |
|------|---------|
| `app/api/pipeline_router.py` | `POST /api/pipeline/sweep` endpoint |
| `app/news/dtos/pipeline_dto.py` | `StageSweepResult`, `PipelineSweepResult` |
| `app/news/services/pipeline_orchestrator.py` | Full sweep orchestration + advisory lock |
| `app/news/services/pipeline_sweep_stages.py` | All 7 stage sweep functions |
| `app/news/services/category_mapper.py` | ExtractionCategory → incident_details mapping |
| `scripts/descriptor_recon.py` | Offline descriptor prefix analysis tool |
| `tests/test_pre_extraction_dedup.py` | Pre-dedup stage tests |
| `tests/test_category_mapper.py` | Category mapper unit tests |
| `RECON_FINDINGS.md` | Pre-implementation recon (Tasks 1–6) |
| `RECON_REPORT_RESULTS.md` | Earlier pipeline health recon |
| `DESCRIPTOR_RECON.md` | Task 4 v2 descriptor recon output |

---

## Modified files (summary)

| Area | Files |
|------|-------|
| **Config** | `app/core/config.py` |
| **Extraction** | `extraction_dto.py`, `ollama_extraction_service.py` |
| **Matching** | `match_result_dto.py`, `matching_service.py` |
| **Clustering** | `clustering_service.py`, `pipeline_sweep_stages.py` |
| **Materialization** | `incident_materialization_service.py`, `dedup_matching_service.py` |
| **Repositories** | `incident_repository.py`, `air_violation_repository.py` |
| **API** | `router.py`, `webhooks_router.py` |
| **Frontend** | `IncidentsPage.tsx`, `types.ts` |
| **Scripts** | phase3–5 run scripts simplified to use shared sweep stages |
| **Tests** | extraction, matching, clustering, materialization tests extended |

---

## Test coverage added

| Test file | New / extended coverage |
|-----------|-------------------------|
| `test_pre_extraction_dedup.py` | Near-dup flagged, distinct passes, 48h boundary |
| `test_extraction_service.py` | Comma-split village, JSON array, null village |
| `test_matching_service.py` | Multi-village → 2 `VillageMatchResult` entries |
| `test_incident_materialization_service.py` | 2-village → 2 incidents; dedup high/mid/low/no-embedding; category fields; backward-compat flat match_result |
| `test_clustering_service.py` | Multi-village overlap; partial subsumption orphan rule |
| `test_category_mapper.py` | LA/hospital rollups, DID gating, school keyword, ambiguous fallback, global totals |

**Note**: Full pytest run may require `openpyxl` (imported via `app/news/services/__init__.py` chain). Install project dependencies before running.

---

## Known gaps and follow-ups

1. **Task 0** — Implement CNRS classification trust skip in `FilterRelevanceAction`.
2. **Task 4 v2** — Confirm strip-list (`حرش`, `خراج`, `اطراف`); switch `VillageRepository` to `word_similarity()`; add normalizer + `note_extra` preservation.
3. **Clustering thresholds** — First-pass values; revisit after 2–3 weeks of live backlog data.
4. **Parallel-edit integration** — Tasks 4, 5, 6 all touched `incident_materialization_service.py`; integration re-merge was performed to ensure dedup + category mapping coexist inside the multi-village loop.
5. **Transitivity edge case** in clustering — documented, accepted.
6. **`مشاع` / `وادي` collision** — rely on `word_similarity()` first; do not blind-strip.

---

## Recommended apply order

1. **Deploy code** (all tasks above except Task 2 manual sweep).
2. **Verify config** — `.env` overrides if needed for thresholds.
3. **Run backlog sweep once** — `POST /api/pipeline/sweep` (super-admin) after Tasks 1+3 are live so ~989 pending rows use the cheap path.
4. **Monitor sweep logs** — check `pre_extraction_dedup succeeded=` count vs extraction volume.
5. **Confirm Task 4 v2 strip-list** — run `scripts/descriptor_recon.py` against live DB; approve list; apply v2 diff.
6. **Spot-check incidents** — multi-village shared-bulletin indicator; category fields on `incident_details`; flagged duplicates (`duplicate_flag=true`).

---

## Related documents

| Document | Contents |
|----------|----------|
| `RECON_FINDINGS.md` | Pre-implementation recon + proposals for Tasks 1–6 |
| `RECON_REPORT_RESULTS.md` | Pipeline health, webhook cadence, duplicate pair trace |
| `DESCRIPTOR_RECON.md` | Task 4 v2 descriptor candidate analysis |
