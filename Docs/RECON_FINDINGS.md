# Master Fix Plan — Recon Findings
> **Date**: 2026-08-18 | **Mode**: Read-only fact-finding. No code changes made.

---

## Task 1 — Pre-dedup pass before extraction

### What is available on `raw_messages` before extraction runs

| Column | Available pre-extraction | Notes |
|--------|--------------------------|-------|
| `raw_text` | ✅ | The full bulletin text — the key input for any text-similarity check |
| `message_datetime` | ✅ | Event timestamp from CNRS payload |
| `source_id` / `source_name` | ✅ | Channel identity |
| `cnrs_classification` | ✅ | CNRS's own relevance verdict (already used for Task 0) |
| `external_message_id` | ✅ | CNRS message ID — exact dedup already covered by the DB unique constraint |
| `content_embedding` | ❌ **NOT available** | Generated in `sweep_embedding_generation`, which runs AFTER extraction and matching (step 4 in the 6-stage order: filter → extraction → matching → **embedding** → clustering → materialization). Moving it earlier would require restructuring the pipeline. |

#### Pipeline stage order (confirmed from `pipeline_orchestrator.py`)

```
1. sweep_relevance_filter   ← Step A (LLM)
2. sweep_extraction         ← Step B (LLM)
3. sweep_matching           ← Phase 3 (DB)
4. sweep_embedding_generation  ← Phase 4a  ← content_embedding computed here
5. sweep_clustering         ← Phase 4b
6. sweep_materialization    ← Phase 5
```

The pre-dedup stage would slot in between steps 1 and 2.

### pg_trgm status

**Confirmed enabled.** Migration `alembic/migration/20260811_0006_add_villages_conditions.py` line 20:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm
```

GIN indexes exist on `villages.acs_name`, `villages.ref_name_ar`, and `conditions.action_ar`. **No GIN index exists on `raw_messages.raw_text`** — a full-table `word_similarity()` scan would be needed. At the current scale (~1 000–2 000 rows) a sequential scan completes in milliseconds; worth noting for future scale.

The codebase already uses both `similarity()` (village repository — exact character trigrams) and `word_similarity()` (condition repository — word-level overlap, which outperforms `similarity()` on verbose Arabic sentences). Source:

```python
# app/news/repositories/condition_repository.py line 29
score = func.word_similarity(...)
```

### Proposed approach

**Method: `pg_trgm word_similarity()` in SQL — no embedding model call.**

Rationale:
- The embedding approach would require either moving Phase 4a earlier (pipeline restructure, out of scope) or making a second embedding call per message at pre-dedup time (adds a model call — defeats the purpose of cost reduction).
- `word_similarity()` operates purely in the database, adds zero model calls, and the extension is already enabled. It has already been found superior to `similarity()` for Arabic verbose text in this codebase.
- The downside is no semantic understanding — two messages saying the same thing in completely different words will not be caught. This is acceptable: the purpose is only to catch near-verbatim reposts, not semantic duplicates (which Phase 4 clustering handles with embeddings).

**Proposed time window: last 48 hours** (compared against messages with `status != 'rejected'` and `received_at >= NOW() - INTERVAL '48 hours'`).

Reasoning: The observed burst/backfill pattern shows gaps up to 20 hours between CNRS pushes. A 24-hour window would barely cover that. A 48-hour window gives a 2× safety margin and keeps the comparison set small (at current traffic, ~300–400 rows at most). Comparing against the entire table is unnecessary and gets expensive as months of data accumulate.

**Proposed threshold: I am not ready to give you a number — this is the decision I need your go-ahead on.**

Here is the range with trade-offs:

| Threshold | What it catches | False-positive risk |
|-----------|----------------|---------------------|
| 0.95+ | Near-verbatim copies only (same text with emoji/punctuation differences) | Very low — safe |
| 0.90 | Identical structure with minor word substitutions | Low — conservative |
| 0.85 | Same event with some reworded phrases | Moderate — worth piloting |
| 0.80 | Paraphrases of the same event | Higher — overlaps with what Phase 4 is designed to do |

**My recommendation is 0.92** — conservative enough that it will only fire on obvious near-copies (same bulletin copy-pasted across channels with cosmetic differences), not on genuinely independently-written reports of the same event. A false positive here silently hides a real incident with no recovery path. Better to let 5 near-copies through to Phase 4 (which may catch some with the wider window from Task 3) than to lose one real event.

**Awaiting your go-ahead on the threshold before implementing.**

### What happens to a flagged message

Two options:

| Option | Behavior | Trade-off |
|--------|----------|-----------|
| **A — `status='duplicate'` + `duplicate_of_id`** | Immediately set status to `duplicate` and point `duplicate_of_id` at the similar existing message. Skips extraction entirely. | Consistent with Phase 4 behavior. No schema change. Permanent and irrecoverable if wrong. Log must be detailed. |
| **B — new `status='pre_duplicate'`** | Mark as probable duplicate but leave `extraction_result = NULL`. A human or future audit query can flip these back to `pending` for reprocessing. | Requires adding a value to the `MessageStatus` enum (one-line change + migration) — small schema change. Recoverable. |

**Recommendation: Option A** (`status='duplicate'` + `duplicate_of_id`) with explicit pre-extraction logging (`pre_extraction_dedup: word_similarity={score:.3f} similar_to_raw_message_id={id}`). The threshold of 0.92 is conservative enough to make false positives rare; the detailed log makes the decision auditable. Adding a new enum value + migration for Option B adds friction without meaningful benefit at this threshold.

### Insertion point in `pipeline_sweep_stages.py`

New function `sweep_pre_extraction_dedup()` — async or sync, follows existing stage conventions (`processed/succeeded/failed`, `_format_exception`, per-item isolation). Called between `sweep_relevance_filter` and `sweep_extraction` in `run_full_pipeline_sweep()`.

---

## Task 3 — Clustering window + similarity threshold

### Available data for distribution analysis

This system has only been running for ~5 days and has only **88 parsed messages** with embeddings. That limits the analysis to a single confirmed duplicate pair. The full distribution recon requested in the task plan requires more data than currently exists.

#### Confirmed duplicate pair (from prior RECON_REPORT_RESULTS.md)

| Field | Message 1 | Message 2 |
|-------|-----------|-----------|
| `raw_message.id` | 692124 | 691454 |
| `source_name` | `MTVLebanonNews` | `CNRS Webhook` |
| `village_id` | 976 | 976 |
| `condition_id` | 1 | 1 |
| `event_date` | 2026-08-14 | 2026-08-14 |
| `message_datetime` | 2026-08-14 08:40 UTC | 2026-08-14 04:32 UTC |
| **Time gap** | **248 min (4h 8m)** | — |
| **Cosine similarity** | **0.7675** | — |

Current settings: `cluster_time_window_minutes=90`, `cluster_similarity_threshold=0.90`. This pair fails **both** filters.

#### 16 already-marked duplicates (caught by current settings)

These represent the "easy" cases — within 90 minutes of each other AND cosine ≥ 0.90. They tell us the system can handle near-identical text from the same burst window. They do not tell us anything about inter-channel delay distributions.

#### True-distinct pair sample

No confirmed true-distinct pairs sharing village+condition+event_date were found in the active incidents beyond the one known duplicate pair. The 8 active incidents have unique village+condition+date combinations — no overlap to analyze. This means we cannot currently derive a false-positive floor from real data.

### Limitation statement

**With only 1 confirmed duplicate pair in the dataset, we cannot produce a similarity/time-gap distribution** as requested in the task plan. The correct recommendation based on one data point is:

- **`cluster_time_window_minutes`**: The single known example was 248 minutes. Cross-channel reporting delay in Arabic media for the same event typically ranges from minutes to a few hours (initial bulletin to secondary channel reposts). Recommend **300 minutes (5 hours)** — covers the confirmed case with ~20% margin, and is a natural round number. It would not be unreasonable to go as high as 360–480 minutes for a first setting that can be tightened once more data exists.

- **`cluster_similarity_threshold`**: The confirmed duplicate scored 0.7675. The condition gate (`require_condition_match=True`) provides a second filter, so a lower similarity threshold does not mean unconstrained merging. Recommend **0.75** — just below the confirmed duplicate's score, with the condition gate still blocking same-village-different-condition merges. Going to 0.72 or 0.70 introduces more risk without data to support it.

- **Condition gate**: Keep `cluster_require_condition_match=True`. The confirmed pair had the same `matched_condition_id=1` on both sides, so the gate would have passed. It protects against merging an airstrike report with a road-damage report in the same village.

### Important caveat

These numbers are derived from a single data point. Once the backlog sweep runs (Task 2) and more messages are processed, the distribution will be much clearer. Consider the values above as a first pass to be reviewed after 2–3 weeks of live data, not permanent settings.

### Implementation scope

Only `app/core/config.py` needs changing — update the two values. No logic changes to `ClusteringService` are needed. The `cluster_batch()` union-find and `_are_candidates()` time-window check are both correct; the settings are the only problem.

---

## Task 4 — Multi-village extraction and matching

### Frequency in actual data

One confirmed real case found in extraction results:

```
village = "كفرتبنيت, حرش عيتا الجبل"
```

We cannot query the full set of extraction results with commas without live DB access. Code-level confirmation: `ExtractionResult.village: str | None` (`app/llm/dtos/extraction_dto.py` line 57) — single string, no list support. The LLM prompt (`GENERAL_EXTRACTION_PROMPT` in `ollama_extraction_service.py` line 44) instructs the model to extract the village name as a string. When the bulletin names two villages, the model concatenates them (comma-separated) into the single `village` field because the schema gives it no other option.

The real-world scenario: a common Arabic bulletin style names multiple locations: "استهدف العدو بلدة كفرتبنيت وحرش عيتا الجبل" — same event, two places. This is not rare in war reporting.

### What happens today when the multi-village string reaches `MatchingService.match()`

Trace through `MatchingService.match()` (`matching_service.py` lines 60–80):

1. `extraction_result.village = "كفرتبنيت, حرش عيتا الجبل"`
2. `_match_mention("كفرتبنيت, حرش عيتا الجبل", self.villages.find_similar)` → `normalize_arabic_text(...)` strips diacritics but keeps the comma → `"كفرتبنيت حرش عيتا الجبل"` (4 tokens)
3. `VillageRepository.find_similar("كفرتبنيت حرش عيتا الجبل", limit=5)` calls `func.similarity(normalize_arabic_sql(Village.ref_name_ar), "كفرتبنيت حرش عيتا الجبل")` — pg_trgm computes trigram overlap of a 4-token string against each single-token village name. A 4-token string shares only a fraction of its trigrams with any 1-token name, so similarity scores will be low (~0.3–0.4 at best).
4. `MatchingService.MATCH_THRESHOLD = 0.6`, `LOW_CONFIDENCE_THRESHOLD = 0.35` — likely falls into `matched_low_confidence` (if one of the village names scores ≥ 0.35) or `unmatched`.
5. If `unmatched`: materialization skips the message (`village_match_status='unmatched'` is ineligible). **The incident is never created.**
6. If `matched_low_confidence`: materialization creates an incident with the wrong (partially-matched) village, and the `village_review_required=True` flag is set. The incident exists but points to the wrong village.

**Either way, the second village is lost entirely.** And if another channel reports the same event naming only one village, their `matched_village_id` values differ, so clustering can never compare them.

### Design options

#### Option A — `list[str] | None`: one incident per village

`ExtractionResult.village` becomes `list[str] | None`. Materialization loops over the list and creates one incident per village. Each incident gets the same `condition_id`, `event_date`, `khabar`, etc., but a different `village_id`.

**Pros:**
- Each village appears correctly in the DB and frontend
- Channel A ("village X") and channel B ("village X, village Y") both produce incidents for village X — these have the same `matched_village_id` and can be clustered as duplicates
- No schema change to `incidents` or `incident_details`

**Cons:**
- One raw message → N incidents; the current `Incident.raw_message_id` FK (1:1) still works (N incidents can share the same `raw_message_id`, the FK is not unique)
- The `exact_hash` computation includes `village_id`, so each village gets its own hash — correct, but means N hash checks instead of 1
- Materialization loop logic increases complexity
- Clustering: the "representative" for a multi-village cluster points to one raw_message_id; the second village's incident is created separately and has its own cluster membership — correct behavior

#### Option B — Primary village + JSONB secondary list

Keep `incidents.village_id` as a single FK (to the first matched village). Add a nullable JSONB column `secondary_village_ids` to `incidents`. Store the list of additional matched village IDs there.

**Pros:**
- Smaller schema change (one nullable JSONB column vs. no schema change in Option A)
- Single incident per raw_message

**Cons:**
- Frontend must be updated to display secondary villages
- Clustering still only keys on `matched_village_id` (primary) — cross-channel dedup between "village X" and "village X, village Y" still fails unless clustering is updated to check secondary_village_ids too
- Partial fix: does not fully resolve the clustering gap

### Recommendation

**Option A is recommended**, but this is a scope-expanding change. Before implementing, confirm:

1. Is a 1:N `raw_message_id → incidents` relationship acceptable to the frontend (the list API currently joins `RawMessage` for display fields)?
2. Should both village incidents inherit the same `khabar` (raw text)? Yes — they describe the same event.
3. What happens during clustering — if raw_message_id=692 has incidents for villages 10 and 20, and raw_message_id=691 has an incident for village 10 only, the cluster for village 10 would mark one as duplicate. The village 20 incident from raw_message_id=692 would be orphaned (its source message is marked duplicate). This needs a decision: soft-delete all incidents for a raw_message when it becomes a duplicate, or only the matching-village incident.

**Awaiting your go-ahead on Option A vs B, and the three questions above, before any code is written.**

---

## Task 5 — Wire up or remove `DedupMatchingService`

### Is it genuinely unused?

**Confirmed.** A ripgrep across the entire codebase for all callers of `DedupMatchingService` returned:

```
app/news/interfaces/__init__.py      (exports DedupMatchingInterface)
app/news/services/__init__.py        (exports DedupMatchingService, DEDUP_HIGH_THRESHOLD, DEDUP_LOW_THRESHOLD)
app/news/services/dedup_matching_service.py  (definition)
```

No router, scheduler, seed script, action, or test file instantiates or calls `DedupMatchingService`. The service is exported from `__init__.py` but never imported from there.

### Is the code complete and correct?

The implementation looks logically complete:

- `find_best_match()` correctly calls `IncidentRepository.list_duplicate_candidates()` — that method exists, is implemented (`incident_repository.py` lines 167–197), and uses pgvector cosine distance. ✅
- `merge_into_incident()` correctly calls `IncidentRepository.merge_existing()` — that method exists, is implemented (lines 269–309), and handles casualty max-preservation and note appending. ✅
- The weighted scoring formula (action=0.35, embedding=0.45, time=0.20, sum=1.0 — asserted at line 21) is sound. ✅
- The 3-day time window and 0.80 high / 0.50 low thresholds are hardcoded constants, not in `config.py`. ⚠️

One gap: there is no "flag for human review" path inside `DedupMatchingService` itself. `find_best_match()` returns a score; the caller decides what to do. The mid-range (0.50–0.80) behaviour would need to be implemented in the caller (e.g., create incident with `duplicate_flag=True`).

### Is this pre- or post-materialization?

**Pre-materialization check** — the intended use pattern (based on the method signatures) is:

```
Before creating a new incident from raw_message X:
  → call find_best_match(village_id, condition_id, event_date, embedding)
  → score ≥ 0.80: merge into existing incident (no new incident created)
  → 0.50 ≤ score < 0.80: create new incident with duplicate_flag=True
  → score < 0.50: create new incident normally
```

This is different from Phase 4 clustering, which operates on `raw_messages` before any `incidents` row exists. `DedupMatchingService` operates on `incidents` — it catches cases where a new raw_message would produce a duplicate of an already-materialized incident (e.g., a delayed report arriving days after the original, outside Phase 4's clustering window).

### How it compares to Phase 4

| Aspect | Phase 4 Clustering | DedupMatchingService |
|--------|-------------------|----------------------|
| Operates on | `raw_messages` (before incidents exist) | `incidents` (already materialized) |
| Detection window | 90 min (to be widened to 300 min) | 3 days |
| Similarity method | Cosine on `content_embedding` (raw text) | Cosine on `khabar_embedding` (incident text) + weighted action/time score |
| Threshold | 0.90 (to be lowered to 0.75) | 0.80 (merge) / 0.50 (flag) |
| Condition gate | `matched_condition_id` equality | `incident.condition_id` equality (via action_score) |
| Outcome | Marks `raw_messages.duplicate_of_id`; soft-deletes extra incidents | Merges casualty data into existing incident |

These are complementary, not redundant. Phase 4 handles cross-channel duplicates in the same time window. `DedupMatchingService` would catch delayed reports across days.

### Recommendation

**Wire it in** as a pre-materialization check inside `IncidentMaterializationService.materialize()`, called just before `self.db.add(incident)`. The code is sound; the missing pieces are:

1. Move `DEDUP_TIME_WINDOW_DAYS`, `DEDUP_HIGH_THRESHOLD`, `DEDUP_LOW_THRESHOLD` to `config.py` so they can be tuned without code changes.
2. Add the mid-range "flag" path (create with `duplicate_flag=True`) in the materialization caller.
3. The `khabar_embedding` needed for `find_best_match()` is `representative.content_embedding` — already available on the `RawMessage` object at materialization time.

No new scripts, no new routes. Just a dependency injection of `DedupMatchingService` (requiring `IncidentRepository`) into `IncidentMaterializationService`, and ~20 lines of gating logic.

**Awaiting your go-ahead before implementing.**

---

## Task 6 — Populate "Automated" rollup fields + DID gating

### The key question: does `ExtractionResult` already contain the data?

**Yes — the data exists and is being dropped.**

`OllamaExtractionService.extract()` (`ollama_extraction_service.py` lines 124–187) performs a **three-LLM-call** extraction per message:

1. **Presence gate** (`OllamaPresenceGateService.categories_present()`) — returns the list of category keys that are present in the text (e.g., `[lebanese_army, hospital, vehicles]`).
2. **General fields extraction** (`_extract_general_fields()`) — extracts `village`, `action_description`, and root-level `casualties`.
3. **Per-category detail call** (`OllamaCategoryDetailService.extract_detail()`) — one LLM call **per category key** found in step 1, extracting `did`, `name`, and category-specific `casualties`.

All of this is assembled into `ExtractionResult.categories: dict[ExtractionCategoryKey, ExtractionCategory]` and stored in `raw_messages.extraction_result` as JSONB.

`IncidentMaterializationService.materialize()` reads `ExtractionResult` at lines 62–64 but then **ignores `.categories` entirely** — it only uses `extraction.casualties` (the root-level general casualties).

### What `ExtractionCategory` contains per category

```python
class ExtractionCategory(BaseModel):
    did: DidValue | None = None      # "D" or "ID" — direct/indirect
    name: str | None = None          # institution name, channel name, etc.
    casualties: ExtractionCasualties | None = None  # per-category deaths/injuries breakdown
```

`ExtractionCasualties` has: `total_deaths`, `total_injuries`, `deaths`, `injuries`, `male_deaths`, `male_injuries`, `female_deaths`, `female_injuries`, `children_deaths`, `children_injuries`.

### Mapping from `ExtractionCategoryKey` → `incident_details` columns

| ExtractionCategoryKey | Flag | DID column | Name column | Male D/I | Female D/I | Totals |
|---|---|---|---|---|---|---|
| `lebanese_army` | `la` | `la_did` | — | `lam_d`, `lam_i` | `laf_d`, `laf_i` | `la_td`, `la_ti` |
| `unifil` | `unifil` | `un_did` | — | `unm_d`, `unm_i` | `unf_d`, `unf_i` | `un_td`, `un_ti` |
| `municipality` | `muni` | `muni_did` | — | `munim_d`, `munim_i` | `munif_d`, `munif_i` | `muni_td`, `muni_ti` |
| `hospital` | `hosp` | `hos_did` | `hos_n` | `hosm_d`, `hosm_i` | `hosf_d`, `hosf_i` | `hosd`, `hosi` |
| `health_center` | `hc` | `hc_did` | — | `hcm_d`, `hcm_i` | `hcf_d`, `hcf_i` | `hcd`, `hci` |
| `press` | `press` | `press_did` | `channel` | `pressm_d`, `pressm_i` | `pressf_d`, `pressf_i` | `pressd`, `pressi` |
| `government_building` | `gov` | `gb_did` | `gov_n` | `gbm_d`, `gbm_i` | `gbf_d`, `gbf_i` | `gbd`, `gbi` |
| `vehicles` | `car` | — | — | `carm_d`, `carm_i` | `carf_d`, `carf_i` | `card`, `cari` |
| `school_university` | `school` / `uni` | `sch_did` / `uni_did` | `school_name` / `uni_name` | — | — | — |
| `religious_cultural` | `church` / `mosque` / `ceme` / `releg` / `archeo` | per-entity | per-entity names | — | — | — |
| `road_bridge` | `road` / `bridge` | `road_d_id` | `road_name` / `bridge_name` | — | — | — |
| `emergency_civil_defense` | `emer` | — | — | — | `emer_d`, `emer_i` | — |
| `crossings_other` | `crossing` | — | — | — | — | — |
| `warning_classification` | `warning` / `no_warning` | — | — | — | — | — |
| `casualty_demographics` | *(root, already written)* | — | — | `male_d`, `male_i` | `female_d`, `female_i` | *(children)* |

### Automated rollup fields (to be computed in Python, not requested from LLM)

```
la_td   = (lam_d or 0) + (laf_d or 0)
la_ti   = (lam_i or 0) + (laf_i or 0)
un_td   = (unm_d or 0) + (unf_d or 0)
un_ti   = (unm_i or 0) + (unf_i or 0)
muni_td = (munim_d or 0) + (munif_d or 0)
muni_ti = (munim_i or 0) + (munif_i or 0)
hosd    = (hosm_d or 0) + (hosf_d or 0)
hosi    = (hosm_i or 0) + (hosf_i or 0)
hcd     = (hcm_d or 0) + (hcf_d or 0)
hci     = (hcm_i or 0) + (hcf_i or 0)
pressd  = (pressm_d or 0) + (pressf_d or 0)
pressi  = (pressm_i or 0) + (pressf_i or 0)
gbd     = (gbm_d or 0) + (gbf_d or 0)
gbi     = (gbm_i or 0) + (gbf_i or 0)
card    = (carm_d or 0) + (carf_d or 0)
cari    = (carm_i or 0) + (carf_i or 0)

total_con = (1 if excavator else 0) + (1 if bulldozer else 0)
          + (1 if camion else 0) + (1 if bobcat else 0)
          [+ tracteur — present in model, confirm scope]
```

Global totals on `incidents` (currently set from LLM, to be computed):
```
total_deaths   = (deaths or 0) + la_td + un_td + muni_td + hosd + hcd + pressd + gbd + card + emer_d
total_injuries = (injuries or 0) + la_ti + un_ti + muni_ti + hosi + hci + pressi + gbi + cari + emer_i
```

### DID gating rule

Documented in `incident_detail.py` lines 20–23 (comment only, no enforcement). Rule:

- If flag is `False` / `NULL` → paired `*_did` must be `NULL`
- If flag is `True` → paired `*_did` must be `"D"` or `"ID"` (from `ExtractionCategory.did`)

This is straightforward to enforce at write time in the materialization service: set the flag to `True` when the category is present, set `*_did = category.did` (which the LLM already provides), enforce `*_did = NULL` when the flag is not set.

### Scope verdict

**This is "wire up existing data" — not "extend extraction."** The LLM already extracts all category-level detail on every message. The data sits in `raw_messages.extraction_result` unused. Materialization needs a mapping table (`ExtractionCategoryKey` → `IncidentDetail` field assignments) and the rollup arithmetic. No prompt changes, no new LLM calls, no migration required.

Estimated implementation: one new mapper function in `incident_materialization_service.py` (~80–100 lines), updating the `IncidentDetail(...)` constructor call to include all the mapped fields.

**Complication for `school_university` and `religious_cultural`**: these keys map to multiple boolean flags (school vs. uni; church vs. mosque vs. cemetery). The LLM's `ExtractionCategory.name` field contains the institution name — the mapping from name to specific flag would need either keyword matching or accepting both flags as True when the category is present. This is worth flagging: these two categories are not clean 1:1 mappings and may need a separate convention decision.

**Ready to implement on go-ahead. No blocking questions — but flag the school_university / religious_cultural ambiguity before writing the mapping table.**

---

## Summary of decisions needed before implementation

| Task | Awaiting decision |
|------|-------------------|
| **Task 1** | Approve the `word_similarity` approach; confirm threshold (recommend 0.92; open to your input); approve `status='duplicate'` as the flagging status |
| **Task 3** | Approve `cluster_time_window_minutes=300` and `cluster_similarity_threshold=0.75`; acknowledge these are first-pass values from a single data point |
| **Task 4** | Choose Option A (split into multiple incidents) vs Option B (primary + secondary JSONB); answer the 3 follow-up questions in that section |
| **Task 5** | Approve wiring `DedupMatchingService` into `IncidentMaterializationService`; confirm moving thresholds to `config.py` |
| **Task 6** | Approve the "wire up existing data" plan; decision on `school_university` / `religious_cultural` multi-flag ambiguity |
