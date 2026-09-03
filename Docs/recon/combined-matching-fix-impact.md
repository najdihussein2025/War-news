# Combined Matching-Fix Impact

- Date: `2026-09-03`
- Scope: (1) check `VillageRepository.find_similar()` for the alias/variant
  ranking bug fixed in condition matching (`2abfdef`); (2) measure the real
  combined impact of the village normalization fix (`e2f33a7`) and the
  condition alias + ranking fixes (`75a2a71`, `2abfdef`) across all 426
  currently-`needs_verification` incidents.
- Nothing was written. No incident, `raw_messages.match_result`, migration, or
  reference row was modified. Part 1 required no code change.

---

## Part 1 — `VillageRepository.find_similar()` ranking check

### Finding: the bug is **not present**.

The condition bug (`2abfdef`) was possible because
`ConditionRepository.find_similar()` computes **two** separate SQL expressions
and orders by the second one:

```python
score = func.greatest(word_sim(canonical_ar), word_sim(canonical_en), *alias_scores).label("score")
coverage_rank = (score * func.greatest(word_sim_reverse(canonical_ar),
                                       word_sim_reverse(canonical_en))).label("coverage_rank")
... .order_by(desc(coverage_rank), desc(score), Condition.id.asc())
```

`score` included the alias terms, but the `greatest(...)` **reverse-coverage
factor** inside `coverage_rank` did not. Ordering is by `coverage_rank`, so an
exact alias candidate whose reverse-coverage factor was low could be outranked
by a partial canonical-only candidate. The fix added `*alias_coverage_scores`
to that inner `greatest(...)`.

`VillageRepository.find_similar()` has no equivalent structure. It builds **one**
expression and orders by it directly
([village_repository.py:55-73](../../app/news/repositories/village_repository.py#L55-L73)):

```python
score = func.greatest(
    func.similarity(normalize_arabic_sql(Village.acs_name), normalized_text),
    func.similarity(normalize_arabic_sql(Village.ref_name_ar), normalized_text),
    func.similarity(normalize_arabic_sql(Village.acs_name, compact=True), compact_text),
    func.similarity(normalize_arabic_sql(Village.ref_name_ar, compact=True), compact_text),
).label("score")
rows = self.db.execute(
    select(Village, score)
    .where(...)
    .order_by(desc(score), Village.id.asc())
    .limit(limit)
).all()
```

The **same `score` object** is the SELECTed value returned as the float *and*
the sole `ORDER BY` key. The two compact-key `func.similarity(...)` terms sit
inside that one `func.greatest(...)`, so they raise a candidate's rank by
exactly the amount they raise its returned score. `Village.id.asc()` is a
deterministic, score-independent tie-break. There is no second ranking
expression that could see a narrower set of terms than the score does — the
structural precondition for the condition bug is absent.

### Adversarial test cases (would expose the bug if it existed)

Constructed by taking a two-word Arabic village name and querying its
space-free spelling, where a **different** real village scores higher on the
original-spacing axis than the correct village does on that axis. If ranking
used the original-spacing score only (bug present), the wrong village would be
returned as the top candidate; the compact-key score would appear only as an
inflated number lower in the list.

| query (no space) | correct village | rank-1 under *original-only* score (hypothetical bug) | rank-1 from actual `find_similar()` |
| --- | --- | --- | --- |
| `عينابل` | id 58 `عين ابل` / Ain Ebel | id 142 `عيناب` / Ainab — **0.625, crosses 0.60, wrong village** | **id 58 `عين ابل`, score 1.000000** |
| `كفرعقا` | id 806 `كفر عقا` / Kfar Aaqqa | id 805 `كفرعقاب` / Kfar Aaqab — 0.667, wrong village | **id 806 `كفر عقا`, score 1.000000** |

The actual implementation returns the compact-key-correct village as the top
candidate in both cases, because `desc(score)` orders on the value that
includes the compact-key terms. The bug is not reproducible.

### Re-verification of the six named village examples

Each resolves to the correct village as the **top** candidate (not merely a
high score somewhere in the list); the runner-up is far below.

| raw id | extracted text | top candidate | score | runner-up |
| --- | --- | --- | ---: | --- |
| 1466 | `ديرميماس` | id 518 `دير ميماس` / Deir Mimas | 1.000000 | `ديمان` 0.250 |
| 351 | `كفرتبنيت` | id 857 `كفر تبنيت` / Kfar Tibnit | 1.000000 | `كفربيت` 0.333 |
| 258 | `كفرتبنيت` | id 857 `كفر تبنيت` / Kfar Tibnit | 1.000000 | `كفربيت` 0.333 |
| 1334 | `ديرميماس` | id 518 `دير ميماس` / Deir Mimas | 1.000000 | `ديمان` 0.250 |
| 2921 | `كفرتبنيت` | id 857 `كفر تبنيت` / Kfar Tibnit | 1.000000 | `كفربيت` 0.333 |
| 1593 | `ديرسريان` | id 524 `دير سريان` / Deir Siriane | 1.000000 | `دير كفيفان` 0.267 |

No commit was made for Part 1 (ground rule: no fix when the bug is absent).

---

## Part 2 — Full combined rescore across the 426 flagged incidents

### The rescore completed in this session (~10 s)

Script: [`scripts/phase3-matching/rescore_flagged_incidents.py`](../../scripts/phase3-matching/rescore_flagged_incidents.py).
It is read-only. For every active `needs_verification` incident it re-runs the
exact matcher path (`normalize_arabic_text` → `VillageRepository.find_similar` /
`ConditionRepository.find_similar` → the 0.60 / 0.35 ladder, including the
id 2 / 39 distinguishing-token guard) for every **stored** target village
mention and the stored condition mention, then classifies the incident.
Live pg_trgm queries are cached per distinct mention string.

- 426 active `needs_verification` incidents, across 267 distinct representative
  `raw_messages`.
- "Match fully clears" = condition **and every stored target village mention**
  now land `matched` (≥ 0.60).
- "Would auto-clear now" = match fully clears **and** no non-match uncertainty
  signal. `duplicate_flag` is the only such signal present on the current 426
  (relevance / insufficient-score / casualty-transition signals are all absent
  per `verification-status-fix.md`).

### Headline

| outcome | incidents |
| --- | ---: |
| flagged before any fix | **426** |
| match fully clears now (condition + all target villages ≥ 0.60) | 50 |
| &nbsp;&nbsp;→ **would auto-clear now** (no other signal) | **32** |
| &nbsp;&nbsp;→ match clears but still blocked by `duplicate_flag` | 18 |
| still blocked — village only (condition ≥ 0.60, ≥1 target village < 0.60) | 235 |
| still blocked — condition only (all villages ≥ 0.60, condition < 0.60) | 92 |
| still blocked — both | 49 |

`32 + 18 + 235 + 92 + 49 = 426`. After both fixes, **32 incidents (7.5%)** would
auto-clear; **394 remain flagged**.

### Near-miss (0.50–0.599 stored) crossing 0.60 now

Counted per incident mention-entry, matching the `match-confidence-failure-analysis.md`
"entries" methodology (not deduped by shared message).

| dimension | stored near-miss entries | now ≥ 0.60 | crossing rate |
| --- | ---: | ---: | ---: |
| village mentions | 299 | **114** | 38.1% |
| condition mentions | 107 | **55** | 51.4% |

The village figure (114 / 299) reproduces the earlier village-normalization
handoff number exactly. The condition figure (55 / 107) is the first aggregate
measurement — prior condition work only had the 10-case evidence set.

### Why 114 + 55 near-miss crossings yield only 32 auto-clears

Near-miss crossings are per **mention**; auto-clear is per **incident**, and a
flagged incident usually names several places. An incident clears only when
*every* target village mention and the condition clear together.

- Of the 235 **village-only** blocked incidents, the still-failing village
  mentions sit in: moderate (0.35–0.499) 292, near-miss 171, far (< 0.35) 112.
  By worst still-failing band per incident: 136 moderate, 64 far, **35
  near-miss**. Only those 35 are one small threshold/normalization step from
  clearing; the rest need reference aliases, role-aware extraction, or are
  compound/directional locality strings that do not map to a single village.
- Of the 92 **condition-only** blocked incidents, the condition lands near-miss
  in 38 and moderate in 54 after the fix. These are largely multi-action
  digests ("غارة من مسيّرة استهدفت …", "مدفعية الاحتلال … تستهدف …") being
  forced onto one of 45 reference conditions — a coverage problem the eight
  evidence-backed aliases do not span.

### After-fix band distribution (all rescored mentions)

| dimension | matched ≥ 0.60 | near-miss 0.50–0.599 | moderate 0.35–0.499 | far < 0.35 |
| --- | ---: | ---: | ---: | ---: |
| village mentions (2 173 incident-entries) | 1 535 | 199 | 316 | 123 |
| condition mentions (426, one per incident) | 285 | 52 | 86 | 3 |

### What is actually left after both fixes

| residual blocker | incidents | nature |
| --- | ---: | --- |
| village match confidence only | 235 | ~35 near-miss (threshold-adjacent); ~200 moderate/far — reference aliases, compound/directional strings, extraction phrasing |
| condition match confidence only | 92 | multi-action digest text vs. 45 fixed reference conditions; alias catalog coverage gap |
| both village and condition | 49 | combination of the above |
| signal outside match confidence (`duplicate_flag`) | 18 | match now clean; still held by the medium-similarity duplicate flag, which is a dedup-review decision, not a matcher decision |
| **cleared** | **32** | condition + all target villages now ≥ 0.60, no other signal |

---

## Validation

- Part 1 traces and adversarial/named-case checks were run against the live
  backend container repository (`war-news-db-1`, 1 544 active villages).
- Part 2 rescore: `426` incidents, read-only, completed in-session; full
  per-incident detail available via the script's `--json-out`.
- Focused tests: `tests/test_condition_repository.py`,
  `tests/test_matching_service.py`, `tests/test_dedup_matching_service.py` →
  `21 passed, 1 failed`. The single failure,
  `test_generic_strike_does_not_match_warning_or_feigned_with_real_repository`,
  is the pre-existing unrelated integration failure already documented in
  `condition-vocabulary-alias-fix.md` (local DB returns
  `matched_low_confidence` where the test expects `unmatched` for non-alias
  generic airstrike text). No code was changed in this session, so this
  failure is unchanged from `main` HEAD.

## Commits

None. Part 1 needed no fix; Part 2 added only the read-only rescore script
(untracked) and this report.
