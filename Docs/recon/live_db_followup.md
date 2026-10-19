# Live DB damage follow-up (read-only queries, run by you)

Source: `Docs/recon/live_db_damage_audit.sql`. Nothing here was executed by
Claude. The window is approximate (backend recreated 07:23:48 UTC; the full test
run ended before ~07:36 UTC), so it is widened to 07:20–07:45 UTC.

Note: `live_db_damage_audit.sql`, `pipeline_sweep_jobs_recovery.md` and the other
earlier recon files you listed were not present in the repository checkout this
session worked from (they were probably never committed). The audit file was
therefore written from scratch with the same name and window. If you have a local
copy with more queries, keep yours and merge the Q1–Q4 blocks into it.

| Query | Clean result | Damaged result | Recovery action |
|---|---|---|---|
| **Q1** stuck raw messages (`pending`/`parsed` older than 30 min), by state and source | No rows, or only rows whose `received_at` is recent / a known backlog you already tolerate | Many rows in `pending`/`parsed`, especially with `processing_claim_stage` set, all arriving around the window | Run **one bounded** pipeline sweep through the super-admin endpoint, as in `pipeline_sweep_jobs_recovery.md` (small `max_rows`; re-run Q1 afterwards). Do not mass-reset statuses by SQL. |
| **Q2** `pipeline_sweep_jobs` rows | A normal history: finished jobs with sensible `requested_at`/`finished_at`, at most one `pending`/`running` | Table empty or recently truncated (the test ran `DELETE FROM pipeline_sweep_jobs`), or a lone `pending` job created by a test with `use_advisory_lock = false` and no `max_rows` | Empty table is harmless: it is a queue and `ensure_pipeline_jobs_table` recreates it. A stray `pending` unbounded job: let the worker run it only if you want a full sweep, otherwise mark it by hand (your own UPDATE) before the worker claims it. Job history lost is not recoverable except from a dump. |
| **Q3** `pipeline_stage_runs` in window by stage | Only normal worker activity, no `aborted` runs, failures near zero | Bursts of runs with `rows_failed > 0` or `any_aborted = true`, or stage runs from sweep types you did not start | These are logs only. Use them to date the incident; if a stage aborted, run the bounded sweep from Q1. No data repair needed. |
| **Q4a** fixture `sources` | 0 rows | Any row (tests commit when they do not roll back) | Review ids, then write your own DELETE in dependency order (Q4c/Q4d first). Never delete `Red Alert Lebanon`/`CNRS Webhook` themselves: the query only matches them via a 32-hex marker in `external_id`. |
| **Q4b** fixture `villages` | 0 rows | Rows named `Village <hex>`, `Air Village <hex>`, `Arnoun Test <hex>`, `Test Caza` | Same as above; delete only after no incident references them (Q4d). |
| **Q4c** fixture `raw_messages` | 0 rows | Rows like `<hex>-representative`, `<hex>-member`, `message-<hex>`, `telegram:redlinkleb:<hex>` | Delete after dependent incidents/updates (Q4d–Q4f). If any are `pending` they may be picked up by the pipeline workers — act quickly or set them to `rejected` yourself. |
| **Q4d** incidents of fixture sources/villages/raw messages | 0 rows | Any row. These appear on the live map/list | Soft-remove or delete them with your own SQL, children (`incident_details`, `incident_updates`) first. |
| **Q4e** incident_details of those incidents | 0 rows | Rows for fixture incidents | Delete together with Q4d. |
| **Q4f** `incident_updates` in the window | Only updates by real admins/pipeline you recognise | Updates you cannot attribute, or ones for fixture incidents | Inspect individually. Real incident edits in the window stay; fixture ones go with Q4d. |

Reading order: Q2 (what was deleted) → Q1 (what is stuck) → Q3 (timeline) → Q4a–f
(residue). Run the SELECTs inside a read-only transaction
(`BEGIN READ ONLY;` … `ROLLBACK;`) if you want an extra guard.
