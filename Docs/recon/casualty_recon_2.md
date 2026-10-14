# Casualty recon 2 (read-only)

## Summary

The main problem is old data written by an older merge/materialization path; the current checkout also has an auditability gap because several creation/materialization writes do not create an `incident_updates` row. All eight census categories are predominantly pre-image records. No application data or production code was changed.

1. Case 4's final 12 deaths / 10 injuries is fully explained by historical `pipeline_merge` audit rows, not raw 30033's 9/5 extraction.
2. Case 3's 9 injuries came from connected raw 8957, whose text assigns nine injuries to Nabatieh/Maslakh; the incident's root raw 32756 does not supply them.
3. Case 2's 11 was inserted by a merge from raw 8986, a summary whose parenthesized `11` is an attack count, not a casualty count.
4. Case 1 is raw 42520 / incident `4dab80b0-55d2-4f22-a7e1-04df1c4a15da`; it has male deaths 1 with only byline-style `الشهيد` evidence.
5. Case 5 proves the legacy path persisted demographic deaths while leaving its total null; its injury row correctly carries 5 injuries but also a null death total.
6. Current split/materialization code contains scope, gender-evidence and aggregate-bulletin protections absent from the historical worker images.

## Running code vs repo

Backend/pipeline image creation time: **2026-10-14 08:18:57 UTC** (`ef9bbf4c…` / `65938408…`). Reconciliation, backlog, summary and collector worker images were created **2026-10-08 08:19:28 UTC**. The backend application package was copied read-only to `tmp_recon/container_app`; the checkout includes the current scope/backstop and merge protections while the older worker images do not. Relevant current safeguards are `incident_materialization_service.py:2262-2298` (do not distribute aggregate tolls; create a group), `incident_repository.py:1661-1841` (guarded merge plus audit), and `casualty_gender_evidence.py` (evidence-based gender).

## Case identification

| Case | Incident | raw | basis |
|---|---|---:|---|
| 1 | `4dab80b0-55d2-4f22-a7e1-04df1c4a15da` | 42520 | village 409/شقرا; 2026-10-13 14:20:32; deaths/total deaths 1 |
| 2 | `af927dd4-7328-4e90-b941-4e395d5287f3` | 28588 | the unique ٤:٢٧ summary; village 1153; total/reportable deaths 11 |

## Per-case timeline and verdict

| Case | timeline / causal raw | verdict |
|---|---|---|
| 1 | Materialized as 1 male death; no casualty-field audit update identifies a writer. The only qualifying wording is the source/byline `صفحة الإعلامي الشهيد علي شعيب`. | **D** — persisted creation is unaudited; byline false positive is strongly indicated but not proved as the exact writer. |
| 2 | Initial nulls → raw 8986 changes deaths/total deaths to 11 at 2026-09-14 08:21:20 UTC. Its text lists `النبطية الفوقا (١١)` beneath air raids, with no casualty wording. | **B** — legacy `pipeline_merge`; current aggregate/scope handling is intended to suppress this attribution. |
| 3 | Initial root has 1/null; raw 8957 changes both local and total injuries to 9 at 08:23 UTC. Its text explicitly assigns `النبطية حي المسلخ: 9 جرحى`. | **B** — historical merge attributed a related raw rather than preserving root provenance. |
| 4 | 9/5 → 10/12 (raw 5050) → 11/12 (raw 5050/5052) → **12/10** (raw 5310), all `pipeline_merge` updates on 2026-09-07. Raw 5050 says 9/13 but includes 8/11 and 1/2 subevents; raw 5052 says 8/11. | **B** — historical additive/max-style merge leak. Current guarded path is `incident_repository.py:1661-1841`; the current repo does not contain the observed arithmetic writer. |
| 5 | Raw 31308 extraction carries male deaths 2, total deaths 2 and injuries 5. The Arabsalim row (`cbb…`) retains demographic death data/null totals; Kfarroumane (`f88…`) received injury 5 from raw 4040 while totals are inconsistently null. | **C** — older gender inference/materialization caused the bad record; current per-village scope code addresses placement, but totals are not derived from demographic detail when a legacy row already lacks them. |

The complete, chronological evidence is emitted by `scripts/recon/trace_casualty_incidents.py`; it follows ownership, duplicate closure, update provenance and duplicate matches, and prints all available audit rows.

## Writers without an update row

Initial incident creation/materialization writes fields directly (`incident_materialization_service.py:1151-1260`, `1419-1431`, `1597-1814`) and has no corresponding `IncidentUpdate` creation in those paths. Therefore an initial final value cannot always be assigned to a raw from audit history alone. Repository merge writers do add `IncidentUpdate` rows (`incident_repository.py:1448-1457`, `1832-1841`, `1965-1974`).

## Census

Image cutoff: 2026-10-14 08:18:57 UTC. Counts are incident counts; examples are the first five deterministic IDs from the SELECT-only helper.

| category | count | before | after | examples |
|---|---:|---:|---:|---|
| demographic non-null / matching total null | 6 | 6 | 0 | `970268f1…`, `1e870674…`, `a1ec7059…`, `b8bfeecd…`, `cbb16d56…` |
| demographic sum exceeds total | 6 | 6 | 0 | `b1097a42…`, `1a5b73de…`, `3a24451b…`, `14e7607c…`, `baf456b2…` |
| local differs from total, no bulletin group | 2 | 2 | 0 | `e15b8ee6…`, `3b290960…` |
| total above maximum connected extraction | 26 | 26 | 0 | `0b0e4a71…`, `a876b81c…`, `f6d6d8b9…`, `4001e8a2…`, `8ee662bf…` |
| casualty value, no casualty word | 18 | 18 | 0 | `972adbb9…`, `8ee662bf…`, `e6cf9e6e…`, `28ccc77a…`, `fdd35f95…` |
| casualty word only in header/byline | 31 | 31 | 0 | `0b0e4a71…`, `ae3efd5c…`, `636e9cec…`, `84be417a…`, `97c1a63c…` |
| summary-origin with casualty number | 0 | 0 | 0 | — |
| male field with grammatical-only form | 13 | 12 | 1 | `0b0e4a71…`, `636e9cec…`, `1e870674…`, `fbec6690…`, `4dab80b0…` |

## Scoped tests

All passed in the backend image with `pytest -q -x`:

- `test_tier1_split_flow.py`: 10 passed
- `test_tier1_split_casualty_presence.py`: 14 passed
- `test_tier2_detail_fill.py`: 10 passed
- `test_village_role_materialization.py`: 6 passed
- `test_verification_reason_precedence.py`: 3 passed

## Open questions

- The current image/repo diff must be retained with the deployment artifact to prove which historical code revision executed each worker write.
- The 26 census records above extracted maximum need individual historical review before any data correction.
- The raw-to-incident graph has no first-class revision-link audit, so some legacy links are recoverable only from `merged_from` JSON.
