# Summary-flow verification — 2026-10-14

Read-only audit against `docker compose -p war-news` / `war_news_dev`. No database write, migration, container lifecycle operation, or reprocessing script was run.

| Check | Result | Number |
|---|---|---:|
| Recon: deployed image matches `main` | FAIL | image is 5m 42s older than `main` HEAD |
| A1 raw-message continuity, last 72h | FAIL | 72 empty hourly buckets |
| A2 status breakdown | WARN | 1,214 rows; 696 pending |
| A3 non-final older than 2h | PASS | 0 |
| A4 normal incidents / day vs prior 7d | WARN | 0 since T0 vs 288 before T0 |
| B1 summary detection | WARN | 0 detected summaries |
| B2 false negatives | PASS | 0 trigger rows after T0 |
| B3 false positives / fallback | WARN | 0 detected rows to assess |
| B4 delayed unreconciled summaries | PASS | 0 |
| C1-C6 duplicate/casualty/repost safeguards | WARN | 0 summary incidents / 0 summaries |
| D1-D2 late-live enrichment | WARN | 0 pairs to assess |
| E1-E3 matched-item notes | WARN | 0 confirmation notes |
| F1 soft deletes without reason | PASS | 0 |
| F2 soft deletes by reason | PASS | 0 |
| F3 soft-delete constraint | PASS | 1 constraint |
| G1 verification queue / one task per summary | PASS | 0 tasks / 0 duplicate task groups |
| H shadow report | N/A | mode is `off` |

## Deployment facts

- Current mode: `off` (`SUMMARY_FLOW_MODE=off`); configured delay: 90 minutes.
- `T0`: `2026-10-08 11:12:55+00`, the deployment backend image creation time. There is no first summary-flow record: `summary_bulletins` and `origin=summary` are both empty.
- Git `main` HEAD: `dc9fb5919d60e229903e468fe16924ffdb2a4781`, `2026-10-08T14:18:37+03:00`; backend image created `2026-10-08T11:12:55.0236677Z`. Therefore the running image predates the checked-out `main` commit by 5 minutes 42 seconds.
- Deployment DB Alembic revision: `20261008_0079 (head)`, matching the latest repository migration `alembic/migration/20261008_0079_guard_soft_delete_reason.py`.
- Summary schema exists: `summary_bulletins`, `summary_items`, `summary_review_tasks`, and `summary_header_mappings`. Reconciliation outcomes live on `summary_items` (`matched_incident_id`, `created_incident_id`, `reconciliation_status`); review entries live in `summary_review_tasks`.
- A summary-created incident is marked by `incidents.origin = 'summary'` and `source_summary_item_id`; audit decision provenance is `decision_source_summary_id` / `decision_reason`. The Arabic confirmation note is `incidents.note`, written by `app/news/services/summaries/reconcile_service.py:126-135`. A late live message retains `source_summary_item_id` during enrichment (`app/news/services/materialization/incident_materialization_service.py:1411`).
- Soft-delete reason is `incidents.deleted_reason`; constraint `ck_incidents_deleted_has_reason` exists and is `CHECK ((is_deleted = false) OR (deleted_reason IS NOT NULL)) NOT VALID`.
- The strict reconcile path documents the same-village guard and `NEWS_NEVER_ARRIVED`-only creation in `app/news/services/summaries/reconcile_service.py:55` and `:287-318`; condition-family matching is used by `find_matching_incidents` at `:206-211`.

## Evidence and findings

### Recon — FAIL: image/code drift

The deployment image timestamp is earlier than `main` HEAD. That prevents proving the containers run the code represented by the requested commit, even though the database migration is current.

- Likely cause: deployment is a manual pull/build workflow (`RUNBOOK.md:42-49`); no in-container revision label was available.
- Suggested fix: rebuild/redeploy the verified `main` commit through the runbook, then record its immutable revision/image digest. Not performed by this audit.

### A1 — FAIL: raw-message continuity

The last 72 hours contain only the current UTC hour of raw-message intake (28 sources, 1,242 rows); 72 hourly buckets have no `raw_messages`. That includes many daytime two-hour-or-longer gaps.

Examples of the present intake hour: `mehwaralmokawma` 180, `sameralhajali` 158, `Janoubana` 146, `nabatiehchannel` 77, `alichoeib1970` 73.

- Likely cause: operational ingestion/collector availability rather than a summary-flow code decision; no source-level evidence identifies a code file.
- Suggested fix: inspect collector scheduling and its deployment logs, then restore continuous ingestion before any mode transition. Not performed by this audit.

### A2/A3/A4 — WARN / PASS: normal path

Since T0, status counts are: `pending` 696, `parsed` 467, `rejected` 21, `duplicate` 14, `routed_air_violation` 12, and `error` 4. The count of rows in active `pending`/`parsed` states older than two hours is 0 (PASS).

No normal incident was created since T0. The preceding seven days contain 288 normal incidents (daily rows: 34, 181, 29, 39, 5), so the post-T0 per-day rate is down more than 30% (WARN).

- Likely cause: the continuity failure in A1 leaves the normal path without representative post-T0 traffic; this is not sufficient evidence of a materializer defect.
- Suggested fix: restore intake and repeat the rate comparison over complete 24-hour days.

### B–E — WARN: summary flow was not exercised

There are zero detected summaries, summary items, summary-created incidents, confirmation notes, repost groups, duplicate reconciliation groups, late-live enrichment pairs, or summary review tasks after T0. There are also zero post-T0 raw messages containing `ملخص` that were not detected. Thus B2, B4, F, and G zero-count invariants pass, but the detection, fallback, duplicate, enrichment, and confirmation behavior has no real-data evidence.

The direct cause is mode `off`: the pipeline only invokes summary routing when mode is `shadow` or `live` (`app/news/services/pipeline/pipeline_llm_workers.py:59`); the default is also off (`app/core/config.py:53`).

- Suggested fix: after resolving A1 and image drift, enable `shadow`, collect representative summary traffic through the full delay/reconcile window, and rerun this audit before considering `live`. Not performed by this audit.

### F — PASS: soft-delete audit

No soft-deleted incident since T0 lacks `deleted_reason`; no soft deletes occurred since T0. The required constraint is present. Its `NOT VALID` status means it guards new/changed rows but does not prove historical rows were validated; the direct null-reason query returned zero.

### G — PASS: queue invariant

`summary_review_tasks` is empty. Therefore no summary has more than one review entry and the queue is below the warning threshold. This is a zero-data result, not proof of queue behavior under traffic.

### H — N/A

Shadow reporting is not applicable because mode is `off`. `scripts/summary_shadow_report.py` was inspected and not executed: it performs database reads but writes `Docs/audits/summary_shadow_report_<date>.md`, and it imports the locally modified `scripts/reprocess_summaries.py`. Running it was unnecessary and would create an unrequested artifact.

## Answer

**Is the flow safe to keep running / flip to live? No.** It is currently disabled, the deployed image is not demonstrably the `main` HEAD image, intake has a 72-hour continuity gap, and no real summary-flow execution exists to validate detection, reconciliation, duplicate prevention, enrichment, or review-task behavior.

## Query artifact

All database queries are SELECT-only and recorded in `recon/verify_summary_flow.sql`. They were executed with:

```powershell
Get-Content -Raw -Encoding utf8 .\recon\verify_summary_flow.sql | docker compose -p war-news exec -T db psql -U postgres -d war_news_dev
```
