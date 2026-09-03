# System Status and Priorities

- Date: `2026-09-03`
- Purpose: consolidate where each track stands after the matching-fix work, and
  rank what is actually worth doing next.
- Method: repo-grounded only. Every claim below traces to a committed change,
  a `Docs/recon/` doc, or a live read run this session. Three threads referred
  to verbally elsewhere — "Case 1 arbitration", the parked GPU/CPU work, and
  any live-validation thread beyond the casualty-transition one — are **not**
  in the repo and are listed unresolved at the end rather than guessed at.

---

## Track A — Match confidence (incident auto-clear rate)

### Landed

| commit | change |
| --- | --- |
| `e2f33a7` | Arabic name normalization + compact-key village scoring |
| `75a2a71` | eight evidence-backed condition aliases |
| `2abfdef` | condition alias bidirectional-coverage ranking fix |
| `ac1e1b6` | `village_roles` extraction field (target vs. origin) |
| `9ec9a37` | materialize incidents only for target villages |
| `f639e9d` | compute `verification_status` from confidence + uncertainty signals |
| `39e43b6`, `1d8d359`, `e2b4431` | casualty status-transition extraction, merge order, backstop review |

`VillageRepository.find_similar()` was checked for the same ranking-divergence
class as the condition bug and is structurally immune (single scoring
expression, ordered directly) — see `combined-matching-fix-impact.md` Part 1.

### Measured residual (this session, read-only rescore of all 426 flagged)

| outcome | incidents |
| --- | ---: |
| flagged before any fix | **426** |
| would auto-clear now (condition + all target villages ≥ 0.60, no other signal) | **32** |
| match clears but still held by `duplicate_flag` | 18 |
| still blocked — village only | 235 |
| still blocked — condition only | 92 |
| still blocked — both | 49 |

Near-miss (0.50–0.599) crossings: village **114 / 299**, condition **55 / 107**.
The cheap normalization/alias wins are essentially spent: of the 235
village-only blockers, only ~35 are still threshold-adjacent; ~200 sit in
moderate/far bands (compound/directional locality strings, missing reference
aliases, extraction phrasing).

### Open decisions

1. **The 18 `duplicate_flag`-only incidents.** Match is now clean on both
   axes; they are held solely by a medium-similarity dedup flag. This is a
   dedup-review policy call, not a matcher call. Decide: leave flagged
   (conservative) or bulk-review this now well-defined set of 18.
2. **Condition-vocabulary expansion for the 80 single-family messages.**
   `multi-condition-extraction-design.md` Step 1 found that of the 92
   condition-near-miss raw messages, 80 are single-action wording/reference
   mismatches (not genuinely multi-action). Condition is a blocker on
   `92 + 49 = 141` incidents. Same low-risk pattern as `75a2a71` (alias
   catalog keyed by canonical `action_ar`, no migration).
3. **Multi-condition materialization — option A / B / C.**
   `multi-condition-extraction-design.md` is `DESIGN ONLY - AWAITING
   CONFIRMATION`; its recommendation is **C** (defer; only 12 messages are
   truly multi-action; a village×condition cartesian product would invent
   event links). Needs an explicit accept/reject to close or open the thread.
4. **Compound / directional village extraction (largest bucket, ~200
   incidents).** No design doc yet. Strings like
   `بين القنطرة ودير سريان` (0.348), `مشاع المنصوري لجهة مجدل زون`,
   `أطراف بلدة الغندورية لجهة وادي الحجير` do not map to one village by
   trigram score and will not be fixed by aliases or thresholds. Needs a
   scoped design (role-/segment-aware extraction, or a "primary locality +
   modifier" shape) before any code.

---

## Track B — Extraction correctness: casualty status transitions

### Landed

`casualty_transitions` field on Tier-1 general extraction (`injured → deceased`
only), merge-order fix so a transition is applied before max-wins, and a
merge-time backstop that flags `possible_missed_casualty_transition` for review
(`casualty-transition-followup.md`). Schema/prompt-contract validation passes
in CI (golden examples, no live call).

### Open

`casualty-transition-live-validation.md`: live run against `qwen2.5:7b`,
**7 / 10 passed**. The 3 failures are all `transition_plus_restated` — the
model misses an explicit injury-to-death follow-up when the message also
restates a remaining tally. Verdict in the doc: **targeted prompt revision
needed**. The 10-case evaluation set already exists
(`scripts/phase2-extraction-live-check/casualty_transition_eval_cases.json`).

---

## Track C — Pipeline resilience / throughput (items 1–6)

| item | status |
| --- | --- |
| 1 — separate Tier-1 / Tier-2 concurrency pools | **landed.** Isolation confirmed (Tier-1 batch 2.02s → 0.02s under Tier-2 saturation). Defaults 2/2, unchanged. |
| 2 — pre-dedup query narrowing regression | **resolved.** Unindexed `%>` predicate removed; GIN trigram migration is now applied (DB at head `20260903_0049`). |
| 3 — clustering service-level row cap | **landed.** `clustering_max_rows_per_pass` default 100, matches live-sweep call-site cap. |
| 4 — combined Tier-1 presence+extraction call | **closed / gated off.** `item4-tier1-combined-call-full-eval.md`: "not viable to enable" — combined path regresses precision (adds false presence categories) and the 43-row corpus can't support a proper accuracy gate. Flag `tier1_use_combined_presence_extraction` stays `false`. |
| 5 — batched Tier-2 category-detail call | **gated off, pending eval.** `tier2_use_batched_category_detail=false`. ~57% call reduction at mean load, but only a trivial n=2 agreement check ran. Needs the category-rich full comparison before enabling. Low current urgency: 0.43 categories/message mean. |
| 6 — Tier-1 concurrency raise to 3/4 | **closed.** Verdict "stay at 2" — pool 4 measured slower than pool-2 baseline; pool 3 never produced a completed run. |

---

## Track D — Observability (Phase A, items 1–6)

**Landed** (`observability-implementation-report.md`, commits `bd51b6d` …
`f14a59d`): `pipeline_stage_runs` telemetry table, 8 per-row stage timestamp
columns on `raw_messages`, per-stage queue depth + oldest-waiting age, latency
percentile summary, live-sweep cursor-gap check, admin pipeline health view.
Human-visible data only — no automated alerting or SLO gate.

`cursor-gap-followup.md`: the false `unhealthy` alert was diagnosed as benign
(CNRS pre-classified traffic never touches the relevance-filter stage, so its
cursor legitimately idles). Health check reworked to track relevance-eligible
backlog instead of raw ID-space gap (`ea277e6`, `0c5e387`).

---

## Migration & config state

- DB is at single head `20260903_0049`. No unapplied migrations, no
  uncommitted migration files.
- Gated-off feature flags (all default `false`, safe to leave):
  `tier1_use_combined_presence_extraction`,
  `tier2_use_batched_category_detail`.
- Tier concurrency: `TIER1_LLM_MAX_CONCURRENT_REQUESTS` /
  `TIER2_LLM_MAX_CONCURRENT_REQUESTS` both 2 (do not raise per item 6).

---

## Threads needing your input (excluded above)

| thread | what's missing |
| --- | --- |
| "Case 1 arbitration" | no `Docs/recon/` file uses this label; `match-confidence-failure-analysis.md` frames failures as village-only / condition-only / both and near / moderate / far bands, not numbered cases. Point me at the source or restate the item. |
| parked GPU/CPU work | nothing in the repo. `item6-concurrency-recommendations.md` covers Ollama request concurrency only, and could not confirm server-side saturation. |
| live-validation thread(s) | the only live-validation artifact is `casualty-transition-live-validation.md` (Track B above). If there is a broader validation effort, it isn't recorded. |

---

## Recommended next, ranked

1. **Decide the 18 `duplicate_flag` incidents** — smallest, fully bounded,
   unblocks a clean set immediately or closes the question.
2. **Condition-vocabulary expansion for the 80 single-family messages**
   (Track A open decision 2). Highest match-clear leverage left at low risk;
   reuses the `75a2a71` alias pattern; no migration. This is also the
   prerequisite the multi-condition design named before revisiting cardinality.
3. **Casualty-transition prompt revision** (Track B). A correctness bug
   (undercounted deaths on restated follow-ups), small surface, evaluation set
   already built — re-run to 10/10.
4. **Scope compound/directional village extraction** (Track A open decision 4).
   The largest residual bucket (~200 incidents) but needs a design doc and an
   extraction-shape decision first — not a quick fix.
5. **Confirm or reject multi-condition option C** (Track A open decision 3) —
   one decision that either closes the thread or opens the 12-message
   sub-event model.

Not now: item 5 batched Tier-2 eval (throughput only, gated, load is light);
item 4 (closed); item 6 (closed); raising tier concurrency.
