# Pipeline Recon Report — 2026-08-18

> **Mode**: Read-only fact-finding. No changes made to any file or database.

---

## 1. Webhook cadence

### Route handler

**File**: `app/api/webhooks_router.py` (lines 15–26), handler `receive_cnrs_posts`

```
POST /webhooks/cnrs-posts?source_id=3
  → verified by verify_cnrs_webhook_secret dependency
  → ReceiveCnrsWebhookAction.execute() (app/sources/actions/receive_cnrs_webhook_action.py)
```

`received_at` is **not set in Python code**. It is set entirely by the PostgreSQL `server_default=func.now()` on the `raw_messages.received_at` column (`app/news/models/raw_message.py`, line 100–103). This means `received_at` reflects the DB insert time, which is effectively the moment the webhook handler calls `self.sources.add_raw_message(...)` (line 66 of `receive_cnrs_webhook_action.py`).

### Hourly cadence (all-time, UTC)

```
2026-08-13 09:00  →   1 msg
2026-08-13 10:00  →   1 msg
(20h gap: 2026-08-13 10:00 → 2026-08-14 06:00)
2026-08-14 06:00  → 103 msgs  ← burst/backfill
2026-08-14 07:00  →   8 msgs
2026-08-14 09:00  →   2 msgs
2026-08-14 10:00  →   3 msgs
(2d 20h gap: 2026-08-14 10:00 → 2026-08-17 06:00)  ← LARGEST GAP
2026-08-17 06:00  → 749 msgs  ← burst/backfill
2026-08-17 07:00  →   3 msgs
2026-08-17 08:00  →  22 msgs
2026-08-17 09:00  →   2 msgs
2026-08-17 10:00  →  13 msgs
2026-08-17 11:00  →  45 msgs
(19h gap: 2026-08-17 11:00 → 2026-08-18 06:00)
2026-08-18 06:00  → 160 msgs  ← burst/backfill
```

**Total: 1,112 messages across only 13 distinct receive-hours over ~6 days.** The expected pattern of one push per hour producing a roughly flat hourly distribution is not present. Instead, the system receives bursts (749, 160, 103) then goes silent for up to 2 days 20 hours.

**Gaps exceeding 2 hours:**

| Gap start (UTC)      | Gap end (UTC)        | Duration        |
|----------------------|----------------------|-----------------|
| 2026-08-14 10:00     | 2026-08-17 06:00     | **2 days 20 h** |
| 2026-08-13 10:00     | 2026-08-14 06:00     | 20 h            |
| 2026-08-17 11:00     | 2026-08-18 06:00     | 19 h            |

### `message_datetime` vs `received_at` lag distribution

The lag between `message_datetime` (when the event occurred) and `received_at` (when ingested) ranges from **1 minute to 6,971 minutes (~116 hours)**. A live pipeline would show most messages with lag <30 minutes. Instead:

- ~150 messages: lag 1–170 minutes (live-ish)
- Hundreds of messages: lag 300–7000+ minutes (backfill — events days old arriving in bulk)

The dominant pattern is **backfill**: large batches of old messages being pushed at once (e.g., the 749-message burst at 2026-08-17 06:00 contains messages from days prior).

### Idempotency / silent-drop risk

`receive_cnrs_webhook_action.py` lines 82–87 catch `IntegrityError` on the `uq_raw_messages_source_external_message` unique constraint; such messages are silently counted as `duplicates` and not re-inserted, but they do not raise or set `status=error`. The outer `except Exception` (line 88–93) logs an exception and increments `failed` but also does not raise — the endpoint always returns 202 with a count summary. **A message that fails for any reason (including parse errors on the DTO) silently disappears into the `failed` counter without leaving a row in `raw_messages`.**

The DTO (`CnrsWebhookPostDTO`) has `model_config = ConfigDict(extra="allow")` so unknown fields are accepted, and `raw_text` is optional (`str | None`). A post with missing `external_message_id` would cause a Pydantic validation error at the outer `CnrsWebhookPayload` parse level (before the action runs), returning a 422 — the only path that is not silent.

---

## 2. Message pipeline health

### Status breakdown (all rows; 7-day window is the same since oldest rows are ~5 days old)

| Status    | Count | Notes                                        |
|-----------|-------|----------------------------------------------|
| pending   | 997   | Unprocessed — waiting for Step A             |
| parsed    |  88   | Completed Steps A, B, Phase 3 at some point  |
| duplicate |  16   | Marked duplicate by Phase 4 clustering       |
| rejected  |  11   | Filtered out by Step A (not relevant)        |
| **error** |   0   | No messages currently in error state         |

**Total: 1,112.**

### Error-status rows

Zero rows have `status = 'error'` in the database. This does not mean no errors have occurred; it means any message that errored during Steps A or B had its status set to `error` temporarily and was presumably retried, or errors were reset. No persistent error accumulation is visible.

### Stuck messages

**837 messages** are `status = 'pending'` with `filter_result IS NULL` and `received_at` older than 4 hours (i.e., have never been touched by Step A):

- Oldest: `2026-08-14 10:13:41 UTC`
- Newest among stuck: `2026-08-17 11:00:22 UTC`

Age breakdown:

| Bucket            | Count |
|-------------------|-------|
| > 3 days old      |     3 |
| 1–3 days old      |   749 |
| 4 h – 1 day old   |    85 |
| Recent (< 4 h)    |   160 |

The 749 messages 1–3 days old correspond exactly to the Aug 17 06:00 UTC burst. They have never progressed through Step A.

### Pipeline trigger mechanism — root cause

The pipeline steps are **not automated**. Investigation of all five pipeline stages:

| Stage | Trigger mechanism |
|---|---|
| **Webhook receipt** (raw insert) | Runs synchronously inside `POST /webhooks/cnrs-posts` |
| **Step A: relevance filter** | `app/core/seeds/run_relevance_filter.py` — manual CLI script only |
| **Step B: extraction** | `app/core/seeds/run_extraction.py` — manual CLI script only |
| **Phase 3: matching** | `scripts/phase3-matching/run_matching_check.py` — manual script |
| **Phase 4a: embedding** | `scripts/phase4-clustering/run_embedding_generation.py` — manual script |
| **Phase 4b: clustering** | `scripts/phase4-clustering/run_clustering.py` — manual script |
| **Phase 5: materialization** | `scripts/phase5-incidents/run_materialization.py` — manual script |

The scheduler (`app/core/scheduler.py`, lines 8–13) is a **complete no-op**:

```python
def start_scheduler() -> None:
    logger.info("CNRS polling scheduler disabled; webhook ingestion remains active")

def stop_scheduler() -> None:
    return
```

`app/main.py` (line 38) calls `start_scheduler()` on FastAPI startup — which does nothing. No background thread, worker, Celery queue, cron, or APScheduler job is running. The webhook correctly inserts rows into `raw_messages`, but nothing advances those rows through the pipeline unless a human manually runs each script in sequence.

**This is the primary cause of symptom 1 ("new data not inserted" / not appearing as incidents).**

---

## 3. Trust-tier channel table

### Schema

`app/news/models/channel_trust_tier.py` — table `channel_trust_tiers`:

| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | auto-increment |
| channel_name | String UNIQUE | case-sensitive match |
| tier | Enum ('official','trusted','detail') | |
| created_at | DateTime(tz) | server default NOW() |

**There is no explicit numeric rank/priority column.** The tie-breaking rank is derived in code at `app/news/services/clustering_service.py` lines 16–21:

```python
TRUST_TIER_RANK = {
    TrustTier.official: 0,
    TrustTier.trusted: 1,
    TrustTier.detail: 2,
}
UNKNOWN_TRUST_TIER_RANK = 3   # channels with no entry
```

Within the same tier, no secondary ordering exists between channels — tie-breaking falls to `message_datetime` then `id`.

### Current seeded rows (as-is in DB)

| id | channel_name    | tier     | created_at (UTC)          |
|----|-----------------|----------|---------------------------|
| 1  | sameralhajali   | trusted  | 2026-08-17 07:16:05       |
| 2  | bintjbeilnews   | trusted  | 2026-08-17 07:16:05       |
| 3  | alichoeib1970   | trusted  | 2026-08-17 07:16:05       |
| 4  | NNALeb          | official | 2026-08-17 07:16:05       |
| 5  | Janoubana       | detail   | 2026-08-17 07:16:05       |
| 6  | nabatiehchannel | detail   | 2026-08-17 07:16:05       |
| 7  | alimortada963   | detail   | 2026-08-17 07:16:05       |

### `bintjbeilnews` duplicate-tier finding

**Refuted.** `bintjbeilnews` appears exactly **once** in the DB (row id=2, tier=`trusted`). The `channel_name` column has a `UNIQUE` constraint (migration `20260814_0018` line 74) that would prevent a duplicate insert. The known-open issue does not manifest in the current database state.

### Effective priority ranking (for clustering representative selection)

1. `NNALeb` — official (rank 0) — **highest priority**
2. `sameralhajali`, `bintjbeilnews`, `alichoeib1970` — trusted (rank 1) — no intra-tier ordering confirmed
3. `Janoubana`, `nabatiehchannel`, `alimortada963` — detail (rank 2)
4. Any unlisted channel — rank 3 (lowest priority)

### Channels in traffic with no trust-tier entry

23 distinct `source_name` values appear in `raw_messages` with no matching row in `channel_trust_tiers`. Each has only 1 message, suggesting they are one-off or secondary sources. Full list:

```
alakhbar_news, AlakhbarNews, ALJADEED_NEWS, ALJADEEDNEWS, almanarnews,
almayadeen, AlMayadeenNews, almodononline, Annahar, Beirutfirebrigade,
breakingnews_mt, CivilDefenseLB, CNRS Webhook, fouadkhreiss, hashemsayed,
LBCI_NEWS, Lebanon24, lebanondebate, manarbreaking, mehwaralmokawma,
MTVLebanonNews, nbntweets, NidaaWatan
```

Any message from these channels that is clustered against a trust-tier channel will lose (rank 3 vs. 0/1/2), meaning it will be marked as duplicate, not as the representative. If a message from `MTVLebanonNews` is the **only** channel to have reported an event, it still gets an incident — the trust-tier only matters for tie-breaking inside a cluster.

**Notable**: `LBCI_NEWS` and `MTVLebanonNews` appear in parsed messages and have incidents, confirming they do participate in the pipeline without trust-tier entries.

---

## 4. Clustering / dedup

### Phase 4 clustering code

**File**: `app/news/services/clustering_service.py`

**Cosine similarity function** (lines 25–44): Implemented in pure Python (no pgvector in-DB computation). Returns 0.0 if either embedding is None.

**`should_merge(left, right)`** (lines 144–155): The two-signal merge rule:
1. Compute cosine similarity → if `< self.similarity_threshold` (default 0.90), return False immediately.
2. If `require_condition_match` is True (default), also check `conditions_allow_merge()`.

**`conditions_allow_merge(left, right)`** (lines 67–84): Both messages must have `condition_match_status` in `{"matched", "matched_low_confidence"}` AND must have the same `matched_condition_id`. So `matched_low_confidence` **does** count as a valid condition match for merge purposes.

**`find_candidates(raw_message)`** (lines 114–142): Queries DB for other `status=parsed` messages with non-null embedding, same `matched_village_id`, and `message_datetime` within ±`time_window_minutes` (default 90 min). This is the per-message incremental approach (used when running one message at a time).

**`cluster_batch(messages)`** (lines 171–199): Union-find over all messages passed in. The script `run_clustering.py` calls `_cluster_all_eligible()` which loads **all** `status=parsed`, `content_embedding IS NOT NULL`, `match_result IS NOT NULL`, `duplicate_of_id IS NULL` messages and runs `cluster_batch()` on the full set — so it does not lose pairs that are >N hours apart (the time-window filter is re-applied inside `_are_candidates` within the batch). **The batch window is still 90 minutes**, so messages more than 90 minutes apart in `message_datetime` will never be considered even in the full batch.

**Current settings** (`app/core/config.py`):

```python
cluster_time_window_minutes: int = 90
cluster_similarity_threshold: float = 0.90
cluster_require_condition_match: bool = True
```

### Embedding coverage

| Scope | With embedding | Without embedding | Total parsed |
|---|---|---|---|
| Last 7 days | 88 | 0 | 88 |
| All time | 88 | 0 | 88 |

**100% of parsed messages have embeddings.** Embedding absence is not a contributing factor to the duplicate problem for the current dataset.

### Trust-tier usage in merge logic

**Found.** `ClusteringService._trust_rank()` (lines 213–222) calls `ChannelTrustTierRepository.get_tier_by_channel_name(channel_name)` using `message.source_name` (line 214). The result is used in `pick_representative()` (lines 157–168) as the primary sort key: lowest rank wins (official beats trusted beats detail beats unknown).

**Gap**: The lookup uses an exact case-sensitive string match (`ChannelTrustTier.channel_name == channel_name`). If `source_name` in `raw_messages` differs in casing from the seeded entry (e.g., `"NNALeb"` vs `"nnaleb"`), the lookup returns None and the channel gets `UNKNOWN_TRUST_TIER_RANK = 3`. No case-normalisation is applied at insert or at lookup time.

### Real duplicate pair — traced example

Only 1 pair of active (non-deleted) incidents sharing the same village, condition, and event_date was found:

| Field | Incident 1 | Incident 2 |
|---|---|---|
| `incident.id` | `016d3b5b-...` | `30b51570-...` |
| `raw_message.id` | 692124 | 691454 |
| `source_name` | `MTVLebanonNews` | `CNRS Webhook` |
| `village_id` | 976 | 976 |
| `condition_id` | 1 | 1 |
| `event_date` | 2026-08-14 | 2026-08-14 |
| `message_datetime` | 2026-08-14 08:40 UTC | 2026-08-14 04:32 UTC |
| `village_match_status` | matched | matched |
| `condition_match_status` | matched_low_confidence | matched_low_confidence |
| `matched_condition_id` | 1 | 1 |

**Time gap between messages**: 4 hours 8 minutes (248 minutes), which exceeds the 90-minute clustering window.

**Cosine similarity** (computed via pgvector `<=>` operator): **0.7675**

**Merge rule trace**:

1. Time window check (`_are_candidates`): abs(248 min) > 90 min → **these two messages are NEVER presented to `should_merge()`**. The clustering script would not even compare them.
2. Even if the window were wider: cosine 0.7675 < 0.90 threshold → `should_merge()` returns False.
3. Condition gate: both statuses are `matched_low_confidence`, both `matched_condition_id = 1` → `conditions_allow_merge()` would return True — the condition gate is not the blocker.

**Why both became incidents**: The 90-minute time window caused them to be in separate clusters (or rather, both are singletons since no other message is within 90 min with the same village). Each was materialized as an independent incident. The `exact_hash` (SHA-256 of raw_text + village_id + condition_id + date) differs because the raw_text from `MTVLebanonNews` ≠ raw_text from `CNRS Webhook` (different wording of the same event).

**The `DedupMatchingService`** (`app/news/services/dedup_matching_service.py`) is a separate, weighted-score system (weights: action=0.35, embedding=0.45, time=0.20; high threshold=0.80) intended to run against the incidents table. It is **not wired into any automatic pipeline** — no API endpoint, no script call found in any router, scheduler, or seed script that invokes it.

---

## 5. Multi-village gap

### Finding

**The extraction pipeline assumes exactly one village per message.** `ExtractionResult.village` is defined as `str | None` — a single string (`app/llm/dtos/extraction_dto.py`, line 57):

```python
village: str | None = None
```

`MatchingService.match()` (`app/news/services/matching_service.py`, lines 60–80) passes this single string to `self.villages.find_similar(normalized, candidate_limit)` — a trigram similarity query against `ref_name_ar`. There is no splitting, looping, or multi-village handling anywhere in the pipeline.

### Real-world evidence

One extraction result in the DB has `village = "كفرتبنيت, حرش عيتا الجبل"` — the LLM output two villages as a comma-separated string. When this string is passed to `find_similar()`, the trigram engine attempts to match the entire concatenated string against single village names. It may return a low-confidence match against one of them, or no match at all.

**Consequence for deduplication**: If channel A reports "Event in village X" and channel B reports "Event in village X, village Y" (a common bulletin style), their matched_village_id values will differ (X vs. whatever the trigram query matches for the combined string). Since clustering requires same `matched_village_id`, these two messages will **never be compared** by the clustering service, even if they describe the same event.

---

## 6. Extraction → `incident_details` automated field population

### Code paths

**`IncidentMaterializationService.materialize()`** (`app/news/services/incident_materialization_service.py`, lines 35–139) writes the following to `incident_details`:

```python
IncidentDetail(
    incident_id=incident.id,
    male_d=casualties.male_deaths,
    male_i=casualties.male_injuries,
    female_d=casualties.female_deaths,
    female_i=casualties.female_injuries,
    children_d=casualties.children_deaths,
    children_i=casualties.children_injuries,
)
```

Only 6 sub-fields are populated. All other `incident_details` columns — `la_td`, `la_ti`, `un_td`, `un_ti`, `muni_td`, `muni_ti`, `hosd`, `hosi`, `hcd`, `hci`, `pressd`, `pressi`, `gbd`, `gbi`, `card`, `cari`, `total_con`, and all flag columns (`la`, `unifil`, `muni`, `hosp`, `hc`, `press`, `gov`, `car`, etc.) — are **never written by the materialization service**. They remain NULL for all automatically-materialized incidents.

### "Automated" rollup fields — LLM vs computed

**`total_deaths` and `total_injuries` on the `incidents` table** are populated directly from the LLM's `ExtractionCasualties.total_deaths` and `ExtractionCasualties.total_injuries` fields (lines 91–92 of `incident_materialization_service.py`). These are values the LLM was asked to emit, **not computed from sub-fields** — this violates the "Automated" specification.

No code anywhere in the codebase (action, service, repository, or script) computes rollup fields such as:
- `la_td = lam_d + laf_d`
- `un_td`, `muni_td`, `hosd`, `hcd`, `pressd`, `gbd`, `card`
- `total_d = deaths + la_td + un_td + muni_td + hosd + hcd + pressd + gbd + card + ...`
- `total_inj` equivalent
- `total_con = Excavator + Bulldozer + Camion + Bobcat`

These fields are present in the `incident_details` schema (`app/news/models/incident_detail.py`) but are never populated in the pipeline.

### `*_did` gating rule

The DID gating rule (lock `*_did` when parent flag is 0; require it when flag is 1) is acknowledged in a code comment at `app/news/models/incident_detail.py` lines 23–24:

```python
# DID convention: for every *_did field paired with a controlling flag
# (for example, la + la_did), the _did value should be null when the flag is
# false/null and "D" or "ID" when the flag is true. This is enforced later at
# the application layer, not by a database constraint in this migration.
```

**No application-layer enforcement was found.** `IncidentMaterializationService` does not validate or set any `*_did` field. The parent flags (`la`, `unifil`, `muni`, etc.) are also never set. The rule is documented but unimplemented.

### Spot-check: 5 most recent active incidents

| incident.id (prefix) | total_deaths | total_injuries | deaths | injuries | male_d | … all detail sub-fields |
|---|---|---|---|---|---|---|
| 016d3b5b | NULL | NULL | NULL | NULL | NULL | **all NULL** |
| 30b51570 | NULL | NULL | NULL | NULL | NULL | **all NULL** |
| 0beb2663 | NULL | NULL | NULL | NULL | NULL | **all NULL** |
| ee7aa9f7 | NULL | NULL | NULL | NULL | NULL | **all NULL** |
| 13cbfdc2 | NULL | NULL | NULL | NULL | NULL | **all NULL** |

Computed sum check: `COALESCE(male_d,0)+COALESCE(female_d,0)+COALESCE(children_d,0) = 0` for all 5 (all inputs are NULL). No mismatch between `total_deaths` and sub-field sum because all are NULL. The LLM did not extract any casualty figures for these events (they appear to be non-casualty incidents such as airstrikes on property), which is legitimate — but the rollup fields remain uncomputed regardless.

---

## Summary: most likely root causes

### Symptom 1: "New data not inserted" (messages not appearing as incidents)

**Root cause 1 — No automated pipeline runner** _(certainty: confirmed)_

The scheduler is a no-op. Steps A (filter), B (extract), Phase 3 (match), Phase 4a (embed), Phase 4b (cluster), and Phase 5 (materialize) are all manual CLI scripts. As of 2026-08-18 09:35 UTC, **837 messages** are stuck in `pending` status awaiting Step A, the oldest from 2026-08-14. The webhook correctly inserts rows, but no background process advances them. Evidence: `app/core/scheduler.py` lines 8–13; DB query showing 837 stuck pending rows.

**Root cause 2 — Burst/backfill cadence, not hourly push** _(certainty: confirmed)_

CNRS is not pushing one batch per hour as expected. It delivers large backfill bursts (749, 160, 103 messages at once) with gaps of up to 2 days 20 hours. No messages arrive at all for most hours. This pattern does not cause lost data at the webhook layer (all inserts succeed), but it concentrates all the pipeline load at the manual-run moments and makes the "no hourly arrival" gap invisible to operators.

### Symptom 2: "Same news appearing more than once" (duplicate incidents)

**Root cause 3 — 90-minute clustering window too narrow for cross-channel duplicates** _(certainty: confirmed by traced example)_

The real duplicate pair (village 976, condition 1, 2026-08-14) had messages 4 hours 8 minutes apart. The 90-minute window (both in `ClusteringService.find_candidates()` and `_are_candidates()`) prevented them from ever being compared. Result: two separate incidents for what appears to be one real event. The cosine similarity of 0.7675, even if the pair had been compared, would also be below the 0.90 threshold.

**Root cause 4 — Cosine similarity threshold (0.90) may be too strict for Arabic news paraphrase** _(certainty: supported by evidence, not conclusive)_

The one confirmed duplicate pair scored 0.7675 — semantically similar events described in different words from different sources. The `paraphrase-multilingual-MiniLM-L12-v2` model was designed for this, but Arabic news bulletins from different channels use significantly different wording. 0.90 may eliminate too many legitimate duplicates.

**Root cause 5 — Multi-village bulletin produces only one village match, breaking cross-channel clustering** _(certainty: confirmed in code and data)_

When the LLM returns a comma-separated multi-village string, only one village (or none) is matched. A channel reporting "village X, village Y" will get a different `matched_village_id` than a channel reporting only "village X", preventing the clustering service from ever comparing the two messages. Evidence: `matching_service.py` line 61–64; real extraction result `"كفرتبنيت, حرش عيتا الجبل"` found in DB.

**Root cause 6 — `DedupMatchingService` is implemented but never invoked** _(certainty: confirmed)_

A second, weighted dedup system exists (`app/news/services/dedup_matching_service.py`) that compares incident-level embeddings against a 3-day window of existing incidents with a lower threshold (0.80). This would catch some duplicates that the clustering step misses. However, no API endpoint, scheduler job, or script invokes it. It is dead code in production.

### Additional finding: `incident_details` automated rollup fields never computed

All "Automated" rollup fields (`la_td`, `la_ti`, `un_td`, `un_ti`, `muni_td`, `muni_ti`, `hosd`, `hosi`, `hcd`, `hci`, `pressd`, `pressi`, `gbd`, `gbi`, `card`, `cari`, `total_con`, `total_d`, `total_inj`) are never computed and remain NULL for all automatically-materialized incidents. The `*_did` gating rule is documented in a code comment but has no implementation. The `total_deaths`/`total_injuries` fields on `incidents` are LLM-requested, not computed. Evidence: `incident_materialization_service.py` lines 102–112; spot-check of 5 active incidents — all casualty and rollup fields NULL.
