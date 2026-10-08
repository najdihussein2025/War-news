# Summary bulletin flow status audit — 2026-10-08

## Summary

The flow is **partly built, but not integrated**. A deterministic, data-backed parser, detector, time-window resolver and offline corpus exist in the repository; their last implementation commits are `4db8071..91214b8`.

There is no production call site for `detect_summary`, `resolve_window`, or `parse_summary`: `rg` finds them only in `app/news/services/summaries/` and tests/offline tools. Live summary messages therefore continue through the ordinary Tier-1/materialization path.

The live database has no summary, parsed-item, reconciliation, or review-task schema. Its existing `bulletin_casualty_groups` worker is a different casualty-reconciliation flow. The running backend image also lacks the new summary tests/files, demonstrating code/image drift.

## Status table

| Item | Status | Evidence | What's left |
|---|---|---|---|
| A1 | PARTIAL | `detection.py:9-29`; no production import/call site (`rg` result) | Route detections around Tier 1. |
| A2 | PARTIAL | `window.py:48-87`; tests `test_summary_window.py` | Persist/use window in production. |
| A3 | MISSING | No summary-group model/table; DB table query returned only `bulletin_casualty_groups` | Implement repost grouping. |
| B1 | PARTIAL | `summary_headers.yaml`; `headers.py:87`; 43 `core` entries (not ~48) | Complete/review header coverage. |
| B2 | DONE | `test_summary_parser.py:21-23`; parser compound grammar | Integrate. |
| B3 | PARTIAL | `parser.py:203-210`; `test_summary_parser.py:49-51` | Persist one bulletin review task. |
| B4 | DONE | `parser.py:54-68`; tests `test_summary_parser.py:27-29` | Integrate snapshot with live aliases. |
| B5 | DONE | `parser.py:17,344-364`; `test_summary_parser.py:18-20` | Decide reconciliation anchor. |
| B6 | DONE | lexicon `summary_location_lexicon.yaml:1`; `test_summary_parser.py:24-26` | Persist modifier. |
| B7 | DONE | `parser.py:16,46-51`; `test_summary_parser.py:15-17` | Decide materialization semantics. |
| B8 | DONE | `parser.py:407-412`; `test_summary_parser.py:36-39` merges repeats and retains max count/location texts | Confirm desired repeat policy. |
| B9 | DONE | headers YAML entries; `test_summary_parser.py:45-47` maps explosive Galonat=21, Lanchar=13, Apache/drone strikes=46 | Integrate and validate condition IDs live. |
| C1 | PARTIAL | `test_summary_parser.py:69-72` forbids fuzzy packages | Production matcher still used because parser is not routed. |
| C2 | PARTIAL | `test_summary_parser.py:34-35` rejects one out-of-scope place | Enforce live South/Nabatieh scope. |
| C3 | MISSING | No summary review schema/model; `raw_messages` columns query | Build grouped review persistence. |
| C4 | MISSING | DB query found none of eight requested aliases; only `وادي السلوقي` exists | Seed/commit requested aliases. |
| C5 | PARTIAL | DB: alias `وادي السلوقي` -> village 1464; village 1464 is تولين/مرجعيون/73282 | Add regression checks for Hardinga/Batroun and حدثا/Baabda. |
| D1 | MISSING | Parser has no production call site; normal materializer has fast path (`incident_materialization_service.py:314`) | Add bulletin branch. |
| D2 | MISSING | Normal materializer calls `_collapse_plain_between_targets` at lines 363,1307 | Bypass it for summaries. |
| D3 | MISSING | Normal materializer computes review at lines 129-132/174 | Add bulletin-specific policy. |
| D4 | MISSING | Normal fast path active; no bulletin guard/call site | Guard and test lost-bulletin error path. |
| E1 | MISSING | No summary LLM cross-check service/config; only generic models in `config.py:36,49-50` | Implement configurable larger-model stage. |
| E2 | MISSING | No cross-check code/evidence validator | Implement add-only/evidence invariant. |
| E3 | MISSING | No summary LLM wrapper/retry path | Make parser result independent of LLM failure. |
| F1 | MISSING | `BulletinReconciliationService` is casualty-group reconciliation, not summary parser output | Implement summary item matching. |
| F2 | MISSING | No summary link/note schema | Add confirmation note/link. |
| F3 | MISSING | No summary-created incident path | Add provenance creation path. |
| F4 | MISSING | No summary task model | One task per summary. |
| F5 | MISSING | No summary visibility field/query | Hide fully matched summaries. |
| F6 | DIVERGES | Compose worker lines 119-132 runs every 1800s; service config 60-hour casualty window | Implement summary delay, 1–2h target. |
| F7 | MISSING | No summary incident/casualty provenance | Define/implement casualty dedup. |
| G1 | MISSING | `alembic heads/current`: only applied `20261005_0075`; DB has no summary tables | Create/apply summary migrations. |
| G2 | DIVERGES | `bulletin-reconciliation-worker` is running, compose lines 119-132 | Repurpose/add summary worker only after implementation. |
| H1 | MISSING | `rg summary frontend/src` finds no summary reconciliation hook/API/UI | Build real query/API/UI. |
| H2 | PARTIAL | `IncidentsPage.tsx:422,488,750` has grouped verification UI | Wire summary tasks into this filter. |
| I1 | PARTIAL | terminology YAML plus CHANGELOG summary entries; rules search has no dedicated bulletin rule | Add operational rules and examples. |
| I2 | PARTIAL | 1 approved fixture, 22 pending; `test_summary_golden.py:11-22` | Label 20–30 real fixtures. |
| I3 | PARTIAL | Golden test asserts exact equality, but only 1 approved case; container lacks summary tests | Promote corpus and rebuild image before CI gate. |
| I4 | MISSING | No summary backfill/reprocess script found | Add default-read-only, `--apply`-gated script. |
| J1 | DONE | Fast-path eligibility defines `ERROR_NO_VILLAGE` (`fast_path_eligibility.py:18`) | Test bulletin branch when added. |
| J2 | DONE | Verification policy commits `a53d664`, `12837b4`; live SELECT = 469 needs-verification rows | 469 remains above a low target. |
| J3 | DONE | `config.py:36,49-50`; `.env.dev/.env.main`: relevance gpt-oss:20b, extraction qwen2.5:7b | Add distinct summary-cross-check setting. |

## Repo state

- Branch: `main`; `git status --short` was clean. Branches: `main`, `dev`, and origin counterparts.
- Relevant recent commits: `4db8071` detector, `9cfa841` window, `af68215` parser, `fae1605` fixtures, `b53a583` grammar, through `91214b8` offline CSV reconciliation artifacts. No uncommitted relevant files.
- Alembic: one head, `20261005_0075`; `alembic current` matches it. The known duplicate `20260811_0004` head is not present.
- No summary-flow migration files or applied schema. `raw_messages` has no summary fields; DB summary/bulletin-table query returned only `bulletin_casualty_groups`.
- Compose has a running `bulletin-reconciliation-worker`, but its code (`bulletin_reconciliation_service.py`) reconciles casualty bulletin groups, not parsed summaries.

## Live data findings

`SELECT` found 28 `raw_messages` containing `ملخص` in the prior seven days. The latest five were 41103 (nabatiehchannel, materialized), 41091 (sameralhajali, materialized), 41092 (alichoeib1970, duplicate), 40467 (mehwaralmokawma, duplicate), and 40463 (nabatiehchannel, materialized).

The first two materialized rows produced ordinary incident rows; 41103 produced six and 41091 five, all `auto_processed`; the two duplicate messages produced none; 40463 produced one. No errors were recorded for those five. This is normal Tier-1/fast-path behavior, not the new flow: no summary schema exists and there is no parser call site.

The live alias query confirms `وادي السلوقي` maps to تولين, مرجعيون, ACS 73282. None of the eight requested alias additions were present.

## Missed tasks

1. Integrate detection/window/parser into the pipeline before normal extraction/fast-path materialization, with a durable summary state machine.
2. Add migrations/models for summaries, parsed items, incident links and one review task per summary; then deploy/rebuild so the running image contains the code.
3. Implement strict live alias/gazetteer matching, South/Nabatieh restriction, requested aliases, and regression coverage for known bad matches.
4. Implement reconciliation, provenance notes, delayed scheduling, visibility behavior and casualty non-double-counting.
5. Add the add-only larger-model cross-check with verified evidence spans and parser-safe failure handling.
6. Complete a 20–30-item approved golden corpus and make 100% coverage a runnable CI requirement.
7. Add an `--apply`-gated reprocess/backfill tool; no such tool exists today.

## Open decisions

- **Anchor for `بين X و Y`:** parser represents primary + secondary (`parser.py:344-364`); no reconciliation/materialization policy selects an anchor.
- **Repeats:** parser merges same item and takes the maximum count (`parser.py:407-412`); no documented product decision establishes that behavior.
- **`(٢)` count:** parsed as `reported_count` (`parser.py:16,46-51`), but no incident/reconciliation semantics consume it.
- **Unmapped headers:** the named four are mapped in current YAML/tests, but no approval/mapping policy exists for future headers.
- **Larger model:** no summary-specific env var or chosen model; generic settings use gpt-oss:20b / qwen2.5:7b.

## Risks

- **Highest risk:** the complete parser is dead code in production; summary messages are visibly materialized through the old path.
- **Deployment drift:** Docker’s full suite ran 1,690 pass / 13 fail, but it reported `tests/test_summary_*.py` missing, while those files exist in the working tree. The image/mount is stale.
- **False confidence:** the golden test is exact but only one approved fixture; 22 remain pending.
- **Misleading worker name:** `bulletin-reconciliation-worker` sounds relevant but serves casualty groups only.
- **Alias gap:** required aliases are absent from the live DB, so strict matching cannot resolve them.
- **Verification queue:** 469 live needs-verification rows remains materially above the stated low target.

## Test results

`docker compose exec backend pytest -q`: **1690 passed, 13 failed, 35 warnings** in 24.89s. The 13 failures were missing mounted assets (`Data/Conditions.json`, `Data/Villages.json`, `Data/Database Sample.xlsx`, `Data/VillageLocationAliases.json`), not summary assertions. A targeted summary test invocation could not run because the running container does not contain those new test files.
