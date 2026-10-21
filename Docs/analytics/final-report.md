# Analytics page: final report

Branch `claude/adoring-lamport-o33btx`, one PR into `main`: "Analytics page: data foundation, API, heat map dashboard".
Built and tested in a cloud container against a throwaway PostgreSQL 16 + pgvector (`analytics_cloud_test`, port 5440).
No office database, Docker stack or Ollama was touched.

## What was built

| Stage | Commit | Summary |
|---|---|---|
| A1-A2 schema | `1f0e939` | Migration `20261021_0082` (single head, down_revision `20261019_0081`): `admin_areas`, `villages.admin_area_code`, `action_families`, `condition_families`, `incidents_archive`, `analytics_incident_facts`, `analytics_air_breach_facts`, `analytics_dirty_dates`, plpgsql triggers on incidents, incident_details, bulletin groups/members, air_violations, air_violation_locations (guard `analytics.skip_dirty_marks`). upgrade, downgrade -1, upgrade all pass |
| A3-A7 data foundation | `7643d6b` | `Data/analytics/action_families.json`, `scripts/analytics_load_reference.py`, `scripts/analytics_archive_incidents.py`, fact builders (`status_buckets.py` is the single "headline" definition), refresh service, `scripts/analytics_refresh_sweep.py`, `analytics-refresh-worker` in both compose files, config defaults, runbook + MANUAL-ONLY reset SQL template |
| B API | `93f8745` | `/api/analytics`: meta, map, kpis, timeline, rankings, peaks, matrix, area/{code}, incidents, export.xlsx. `require_admin` on all, Redis cache keyed by `analytics:{version}:{route}:{hash}` |
| C design | `559904d` | `design-system/war-news-analytics/{MASTER.md,pages/analytics.md}` adapted to the admin panel tokens |
| D frontend | `1d12cce` + final commit | Lazy-loaded route in both trees, MapLibre choropleth (feature-state), ECharts timeline, URL-synced filters, rankings, matrix, air section, drawer, methodology modal, Excel export |
| E verify | final commit | Realistic fixture test, screenshots in `Docs/analytics/screenshots/` |

Phase 1 skeleton: commit `037c182` (and `35ee344`) were never pushed to GitHub, so `app/analytics/` did not exist on `origin/main`. The skeleton was recreated inside commit `1f0e939`. If you push those two local commits to a different branch, expect a trivial conflict on `app/analytics/__init__.py` and the empty package folders.

## Deviations from the prompt (and why)

1. **Geojson**: the repo's `lb_village.geojson` has 1,610 features and no `74183` / `disputed` property (the 1,611-feature file with Chebaa Farms was local only). The loader therefore links 1,543 / 1,544 villages today and lists Chebaa Farms as unlinked; with your 1,611-feature file it links 1,544 / 1,544. The loader also marks every `Litige` shape and code `74183` as disputed. I did not touch the geo files.
2. **`analytics_incident_facts.archive_batch`** column added (not in the spec) so "refuse if archive facts for this batch exist" is checkable. It is outside the unique key.
3. **Incident ids are UUIDs** (not integers); archive and exclusion logic use `uuid`.
4. **Conditions are mapped by `action_ar` first, then normalised `action_ar`, then `action_en`** (live ids and some labels differ from the seed). Unmapped conditions fail the loader loudly (dry-run exits 1). At fact-build time an unmapped condition falls back to the `unclassified` (pending) family with a warning instead of breaking the worker.
5. **Air facts are rebuilt globally** (all reports counted at once, exactly like the Air Violations page's data, then rows from `min(dirty date) - 1` forward are rewritten) instead of per-date +-1 day slices. Anchored windows chain forward, so slice-only counting could differ from the page. National totals therefore always equal `count_breaches_by_condition`; `full_rebuild` asserts it.
6. **Incidents with a NULL condition** are skipped by the fact builder (none exist live). Incidents of air conditions (Warplane 17, Surveillance 10 in the live data) stay in the `air_violations` family for incident metrics; breaches are a separate metric.
7. `CAZA_TO_MOHAFAZA` (stale `Zahrani`, `Hasbaya`) was **not** edited; analytics uses its own explicit name-to-HDX-code tables in `app/analytics/constants.py`.
8. The design generator suggested Fira fonts/blue/amber and dark mode; the app's Noto Sans, navy/gold tokens and light-only theme were kept.
9. Reference fixture uses live-like condition ids (Bombs 46, Air Activity 45, Unclassified 87, air ids 34/35/36/38); nothing in analytics code hard-codes them except the pinned air ids already used by the breach service.

## Test results (cloud)

* `tests/analytics`: **86 passed** (status truth table incl. SQL equals Python, parity per date/village/caza/mohafaza, no double count with archive, frozen archive facts, shared toll once, partial demographics, air parity + level rules + unknown bucket, triggers incl. skip guard and irrelevant updates, dirty-queue race, reference loader 26 to 26 cazas, API per endpoint incl. auth/validation/cache/version bump, realistic 420-incident / 320-air fixture).
* Frontend: `vitest` 137 passed (27 files; new: filters/URL state, quantile scale, air-level rules, mappers, geo utils), `tsc` clean, `npm run build` passes.
* Existing suites (air violations, incidents, matching, bulletins): 467 passed, 5 failed, 1 collection error. The same 5 fail on an untouched `origin/main` checkout; the collection error is `tests/test_bulletin_tier2.py` needing `sentence_transformers`, not installed in the container. Not run in cloud: nothing that is analytics-specific.
* Browser check (headless Chromium, fixture data, real Redis): no console errors; page has no horizontal scroll at 1440 and 1024 px. The only non-local requests are the **existing global Google Fonts import** in `frontend/src/styles/tokens.css` (pre-existing, not from this work; blocked offline it falls back to Segoe UI/Tahoma/Arial). Analytics itself calls only `/api` and `/geo`.
* Bundle: main `index` 610 kB (170 kB gzip, unchanged); lazy `AnalyticsPage` chunk 1,360 kB (**398 kB gzip**, maplibre + echarts) + 9 kB gzip CSS.

Screenshots: `Docs/analytics/screenshots/` (full-page, map-mohafaza/caza/village, tooltip, area-panel, rankings, matrix, timeline, air, full-1024).

## COMMANDS FOR HUSSEIN (PowerShell)

Dev stack first (`$d` = prefix), then the deployment stack (same commands without `-p war-news-dev -f docker-compose.dev.yml`, and `db` database `war_news_dev`).

```powershell
# 1. after merging the PR
git checkout main
git pull origin main

# 2. rebuild images and start the new worker (dev stack)
.\scripts\dev.ps1 up -d --build backend frontend analytics-refresh-worker
#    deployment: docker compose up -d --build backend frontend analytics-refresh-worker

# 3. migrate
docker compose -p war-news-dev -f docker-compose.dev.yml exec backend alembic upgrade head
docker compose -p war-news-dev -f docker-compose.dev.yml exec backend alembic heads

# 4. reference data: dry-run, read it, then apply
docker compose -p war-news-dev -f docker-compose.dev.yml exec backend python -m scripts.analytics_load_reference
docker compose -p war-news-dev -f docker-compose.dev.yml exec backend python -m scripts.analytics_load_reference --apply

# 5. build the facts
docker compose -p war-news-dev -f docker-compose.dev.yml exec backend python -m scripts.analytics_refresh_sweep --full

# 6. open http://localhost:5174/admin/analytics  (deployment: http://localhost:5173/admin/analytics)
```

By eye: loader dry-run shows 8/26/1,610 areas, villages linked 1,543/1,544 (1,544 after you add the Chebaa geojson), no UNMAPPED conditions (if some appear, add their `action_ar` to `Data/analytics/action_families.json`); the page headline numbers match the Incidents page (2,815-ish counted live in the recon) and the pending toggle shows 32; Air breaches equal the Air Violations page totals; map level buttons for Warplanes disable caza/village.

Optional analytics tests on the dev stack (never against `war_news_dev_test` itself, they TRUNCATE): create a scratch DB, migrate it, run:

```powershell
docker compose -p war-news-dev -f docker-compose.dev.yml exec db psql -U postgres -c "CREATE DATABASE analytics_scratch_test"
docker compose -p war-news-dev -f docker-compose.dev.yml exec -e DATABASE_URL=postgresql+psycopg2://postgres:YOUR_PASSWORD@db:5432/analytics_scratch_test backend alembic upgrade head
docker compose -p war-news-dev -f docker-compose.dev.yml exec -e ANALYTICS_TEST_DATABASE_URL=postgresql+psycopg2://postgres:YOUR_PASSWORD@db:5432/analytics_scratch_test backend pytest tests/analytics -q
```

When you decide to reset data: follow `Docs/analytics/data-reset-runbook.md` (backup, `analytics_archive_incidents --batch ... --apply`, verify, `analytics_refresh_sweep --archive-batch ... --apply`, `--full`, Excel copy, manual reset from `scripts/manual/analytics_data_reset_TEMPLATE.sql` with `SET LOCAL analytics.skip_dirty_marks = 'on'`, `--full` again).

## Known limits and next steps

* Quantity extraction ("number of strikes per report" via the LLM) is intentionally not built; each incident counts once.
* Ingest-gap signal is a heuristic (days with no `raw_messages.message_datetime` between the first and last ingested day).
* Playback prefetches one `/map` call per frame (daily up to 120 days, weekly beyond); heavy ranges take a few seconds.
* `AirViolationRepository._load_items` / `_breach_report` are private; the air builder calls them to guarantee the same selection as the page. A public wrapper would be cleaner.
* Rankings use incident metrics at village level; village-level air rankings only include helicopters, by rule.
* Air rebuild cost grows with air_violations (fine at ~1k rows; consider windowed rebuild at 100k+).
* `analytics_cloud_test` ran Postgres on port 5440 because the repo's test guard refuses 5432/5433.
