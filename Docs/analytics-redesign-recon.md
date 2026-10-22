# Analytics redesign: Phase 0 recon

Date: 2026-10-22. Read-only. All numbers below are from the dev DB (read-only transaction) unless noted.
Window used for the cross-checks: 30 days, 2026-09-23 → 2026-10-22, verified/counted bucket.

---

## 1. Route and layout (where the sidebar comes from)

- `frontend/src/app/routes.tsx`
  - `/admin` → `<RequireRole roles={[ADMIN]}><AppShell previewRole=ADMIN/></RequireRole>`, child `analytics` (line 125).
  - `/superadmin` → same with `SUPER_ADMIN`, child `analytics` (line 145).
  - Both use the same lazy `AnalyticsPage` (`features/analytics/pages/AnalyticsPage.tsx`) inside `Suspense`.
- `frontend/src/app/AppShell.tsx` renders:
  - fixed 260px `<aside>` sidebar (`SidebarContent`: logos, nav, user + Sign out) at `lg+`, mobile drawer below `lg`;
  - `<main>` with `mx-auto max-w-6xl` (1152px) container: **this is the main cause of the wasted horizontal space**;
  - a sticky page-title bar (`h1` from `pageMeta`, `titleAddon`, `pageAction`) and `ShellContext` (toast, page action).
- The role guard is `RequireRole`, which sits **outside** `AppShell`. A new layout can wrap the analytics route
  inside the same `RequireRole`, so the guard stays exactly the same.

**Plan:** move `analytics` out of the `AppShell` children into a sibling route per role:
`{ path: "/superadmin/analytics", element: <RequireRole roles={[SUPER_ADMIN]}><AnalyticsLayout/></RequireRole> }`
(same for `/admin`). `AnalyticsLayout` is a thin full-width shell (top bar + `<Outlet/>` + `ShellContext` provider).
It reuses `BrandMark`/sign-out logic exported from `AppShell` rather than duplicating the admin layout.
Static routes rank above the `:splat` fallback in react-router v6, so `/superadmin/analytics` matches before `/superadmin/*`.

## 2. Current page components (`frontend/src/features/analytics/`)

| Part | File |
|---|---|
| Page / tabs / layout | `pages/AnalyticsPage.tsx` (tabs are a single page with `hidden` sections, `?tab=` in URL) |
| Filters bar | `components/FilterBar.tsx` (period presets incl. war month `m:YYYY-MM`, custom range, level, family, metric, air type, include pending, reset) |
| Map | `components/HeatMap.tsx` (maplibre), `MapLegend.tsx`, `PlayControls.tsx`, `geoUtils.ts`, `colors.ts`, `analytics.css` |
| Area side panel | `components/AreaPanel.tsx` (opens over the map on area click) |
| KPI cards | `components/KpiCards.tsx` |
| Timeline | `components/TimelineChart.tsx` (+ `EChart.tsx` wrapper) |
| Peaks | `components/PeaksCards.tsx` |
| Rankings | `components/RankingsPanel.tsx` |
| Action × caza matrix | `components/MatrixTable.tsx` |
| Air violations | `components/AirSection.tsx`, `airRules.ts` |
| Drill-down drawer | `components/DrilldownDrawer.tsx` |
| Footer / export / methodology | `components/FooterStrip.tsx` |
| Shared bits | `components/common.tsx` (`SectionCard`, `Skeleton`, `ErrorBlock`, `useInView`) |
| Data layer | `api.ts`, `hooks.ts` (TanStack Query, keys `["analytics", <route>, params]`), `filters.ts` (URL ⇄ filters ⇄ API params), `mappers.ts`, `types.ts` |

Shared app primitives available: `components/ui/DataTable.tsx` (sortable, `DataTableColumn<T>`),
`components/StatusBadge.tsx`, `lib/formatters.ts#formatRelativeTime`.
A persisted design system already exists: `design-system/war-news-analytics/MASTER.md` + `pages/analytics.md`
(UI/UX Pro Max output adapted to app tokens, Okabe-Ito family palette, YlOrRd-7 map scale). Phase 1+ extends
`pages/analytics.md`; it does not replace MASTER.

## 3. Backend endpoints

Router: `app/api/analytics_router.py` (prefix `/api/analytics`, all `require_admin`). Domain: `app/analytics/`
(`dtos/filters.py`, `services/analytics_service.py`, `repositories/analytics_repository.py`). All payloads are
cached in Redis via `analytics_service.cached(route, params)` keyed on a version counter that the refresh worker bumps.

**Shared filter object:** `Filters` (`dtos/filters.py`, built by the `get_filters` dependency): `date_from`, `date_to`,
`level`, `area_code` (+ resolved `area_level`), `family[]`, `condition_id[]`, `include_pending`, `metric`
(`incidents|deaths|injuries|casualties|breaches`). Max range 400 days. The shared WHERE builders are already in place:
`incident_where()` (incident facts) and `air_where()` (air facts). New queries reuse them; no new filter builder is needed.

| Endpoint | Extra params | Source / SQL | Response |
|---|---|---|---|
| `GET /meta` | – | min/max dates, families, area counts, archive batches, dirty-queue size, pending | `incident_data`, `air_data`, `archive`, `families[]`, `area_counts`, `last_refresh`, `refresh_queue`, `pending_review`, `air_conditions`, `air_level_conditions` |
| `GET /map` | filters | `SUM(metric) GROUP BY level col` on facts + per-area family breakdown | `level`, `metric`, `values[{code,value,families?}]`, `unit_note`, `unsupported_air_levels` |
| `GET /kpis` | filters | `incident_totals` (cur + prev period), air totals by type, pending, casualty completeness, 30-day series, sparklines | `incidents/deaths/injuries/villages_affected/cazas_affected/air_breaches` deltas (deaths/injuries carry male/female/children/unspecified), `pending_review`, `casualty_completeness`, `escalation`, `sparklines` |
| `GET /timeline` | `grain=day|week|month` | `date_trunc(grain)` × family (or air type), top 5 + Other, 7-day MA, coverage | `series[]`, `total[]`, `moving_average_7d[]`, `coverage` |
| `GET /rankings` | `limit≤100` | areas at `level` with incidents/deaths/injuries/first/last/dominant family | `rows[]` with `rank` |
| `GET /peaks` | filters | worst day/week for incidents, deaths, breaches + top 3 cazas | `{incidents,deaths,breaches}.{day,week}` |
| `GET /matrix` | filters | caza × family cells | `columns`, `rows[cells,total]`, `column_totals`, `grand_total` |
| `GET /coverage` | dates | `raw_messages` per Beirut day and source vs 28-day median | `days[{date,messages,baseline,status,sources}]` |
| `GET /quality` | filters | geo anomalies, pending, archive cutoff, refresh queue | `geo_anomalies`, `pending_review`, `last_refresh`, `refresh_queue` |
| `GET /incidents` | `page`, `page_size≤100` | raw `incidents ∪ incidents_archive` drill-down | `total`, `items[]` |
| `GET /area/{code}` | filters | area profile: totals, families, conditions, timelines, top children, first/last hit | profile object |
| `GET /export.xlsx` | filters | `export_service.build_workbook` | xlsx |

## 4. Libraries

- Charts: **ECharts 5.5.1** (wrapped by `components/EChart.tsx`). No other chart library; Phase 2 adds no new one.
- Map: **maplibre-gl 4.7.1** with local geojson (`useGeo`).
- Frontend scripts: `typecheck` (`tsc --noEmit`), `test` (vitest), `check`. **There is no `lint` script and no ESLint config**,
  so Phase 5 runs `typecheck` + `test` and says that lint does not exist.

## 5. Fields available to aggregate on

Aggregates read pre-built **daily** fact tables (not raw incidents):

`analytics_incident_facts` grain = `event_date × village_id × condition_id × bucket × source`
columns: `admin_village_code`, `caza_code`, `mohafaza_code`, `family_id`, `bucket (counted|pending)`,
`source (live|archive)`, `incidents`, `deaths_{total,male,female,children,unspecified}`,
`injuries_{…}`, `aggregate_only_incidents`, `casualty_known`.

`analytics_air_breach_facts` grain = `breach_date × condition_id × unit_level × area_code`
columns: `mohafaza_code`, `caza_code`, `breaches`, `reports`, `needs_review_breaches`.

| Field asked for | Available? | Notes |
|---|---|---|
| Incident date | ✅ facts `event_date` | daily |
| Hour of day | ⚠️ raw only | `incidents.event_time` is filled for 2900/2900, but it **equals the raw message's Beirut time in 2900/2900**. It is *time reported*, not *time of event* (peaks at 23h/00h are bulletin hours). Not in facts. Usable only as "hour reported" via a raw-table query, clearly labelled. Air violations: `air_violations.event_time` 883/883 with a plausible daytime distribution, but still the report time. |
| Action family | ✅ `family_id` → `action_families` | |
| Village → caza → mohafaza | ✅ codes on facts | |
| Deaths/injuries split | ✅ male / female / children / unspecified / total | follows the existing children-only + "unspecified = total − typed" rule from `incident_fact_builder` |
| Source / channel | ⚠️ raw only | `incidents.source_id` is **"CNRS Webhook" for every incident** (useless). The real channel is `raw_messages.source_name` / `source_platform` (alichoeib1970, sameralhajali, … telegram/twitter) via `incidents.raw_message_id`. Not in facts. |
| Verification status | ✅ as `bucket` (counted/pending) in facts; full status on raw `incidents.verification_status` (auto_processed 2787, needs_verification 101, verified 6, rejected 6) | |
| needs_verification reason | ⚠️ raw only | `incidents.verification_reason` is **free text** (e.g. "Action could not be classified…" 62, "Possible duplicate…" 14, "Flare wording…" 10). It needs a prefix → category mapping to chart it. |
| Low-confidence village match | ⚠️ raw only | `incidents.quality_flags` JSONB: `low_confidence_village` 242, `unresolved_condition` 41, `flare_wording` 9. Mixed shapes (array / object / JSON null / SQL null) need a defensive query. |
| Archived flag | ✅ facts `source='archive'` | **`incidents_archive` is empty today**, so all facts are live |
| Air violation type | ✅ `condition_id` (34 balloon, 35 warplane, 36 drone/surveillance, 38 helicopter) | level rules in `AIR_LEVEL_CONDITIONS` |
| Data range | facts 2026-08-17 → 2026-10-21 | "War month April = month 1" has **no data before August** in this DB. The war-month table will show empty months, not invent them. |

## 6. Indexes

Facts are already well indexed for the planned GROUP BYs:
`analytics_incident_facts`: `(event_date)`, `(mohafaza_code, event_date)`, `(caza_code, event_date)`,
`(admin_village_code, event_date)`, `(family_id, event_date)`, unique grain.
`analytics_air_breach_facts`: `(breach_date)`, `(unit_level, area_code)`, unique grain.
The table is small (≈2 000 live fact rows), so **no new fact index is needed.**

Raw-table queries planned for the Incidents/Quality tabs (hour reported, channel, verification reason, quality flags)
hit `incidents` (`ix_incidents_active_event_date` partial index exists) joined to `raw_messages` by PK. That is adequate
at ~3 k incidents. I do **not** plan a migration. If one turns out to be needed, it will be generated and not run.

## 7. The three inconsistencies

### 7a. Incidents KPI 1,204 vs Action × caza total 1,196 (8 missing)

Measured: `kpi_incidents = 1204`, `no_caza = 0`, `air_family = 8`, `matrix_total = 1196`.
**The 8 are incidents whose action family is `air_violations`.** `get_matrix()` deliberately drops
`is_air_violation` families (and non-headline families) from the incident matrix, because air violations have their own tab.
The KPI counts every counted incident, air-violation incidents included. No incident is lost to a missing caza or unmatched village.
**Fix (Phase 3):** return `excluded: {air_violations: 8, unclassified: n, no_caza: n}` with the matrix and show a footer row
"+8 air-violation reports (see Air violations tab)". The totals then reconcile on screen, and a test pins
`KPI incidents == matrix grand_total + excluded`.

### 7b. "0% of incidents in this period have a casualty status" while deaths = 8, injuries = 10

Two causes:
1. **Stale facts.** `casualty_known` was added by migration `0083_analytics_casualty_known` (server default 0) in commit
   `feb8102` (2026-10-21 11:23 UTC). The only fact build in the DB ran at 2026-10-21 10:00 UTC (1973 rows, all `casualty_known = 0`).
   Nothing rebuilt the facts afterwards, because **the `analytics-refresh-worker` compose service is not running; it was never created**
   (`docker compose ps -a` does not list it). The dirty queue holds 5 dates (incident 10-21, 10-22; air 10-20..10-22).
   With fresh facts the live data would give ~1 299/1 313 = 99% (`none_mentioned` 1 285, `exact` 7, `explicit_none` 6, `count_missing` 1).
2. **Wrong metric for the sentence.** "has a casualty status" counts `none_mentioned`, so 99% would also be misleading next to deaths = 8.
   The useful number is *incidents with an explicit casualty figure* (`exact` / `explicit_none` / `aggregate_only`) vs *count reported missing* (`count_missing`).
**Fix:** (ops, yours) start the worker and rebuild once:
`docker compose up -d analytics-refresh-worker` then `docker compose exec backend python -m scripts.analytics_refresh_sweep --full`.
(Phase 3, code) split the counter into `casualty_explicit` and `casualty_count_missing`. That needs one new fact column, i.e. one
migration (generated, not run). Alternative with no migration: derive the figure from the existing columns as
"incidents with casualties > 0" plus `count_missing` from the raw table. I recommend the migration because it stays correct under archive facts.
Copy becomes "6 of 1,204 incidents report casualties; 1 reports casualties without a count" in an ⓘ tooltip.

### 7c. "Latest day (2026-10-22): 0 incidents vs 30-day average 40.13 (0×)"

`get_kpis()` uses `escalation.today = by_day.get(flt.date_to, 0)`, and `date_to` defaults to *today* (Beirut). The facts' last date is
2026-10-21 (and that day is partial: 17 incidents vs ~60 typical, still in the dirty queue). Today has no facts at all, so the line reads 0×.
The 30-day average also divides by 30 including today's empty day.
**Fix (Phase 3):** use `latest = min(date_to, max fact date)`. Mark it `incomplete: true` when the date is in `analytics_dirty_dates`
or is ≥ the Beirut date of `last_refresh`. Compute the average over the 30 days *ending the day before* `latest`. The UI then says
"Latest complete day 2026-10-20: 75 vs 30-day avg 41 (1.8×)", or labels the partial day explicitly.

---

## Planned file list (Phases 1–4)

Frontend
- `app/routes.tsx`: analytics routes moved to `AnalyticsLayout` under the same `RequireRole`
- `app/AppShell.tsx`: export `BrandMark` + a `useSignOut` helper (no behaviour change)
- **new** `features/analytics/layout/AnalyticsLayout.tsx`: sticky top bar (← Dashboard, logos, title, freshness, Methodology, Export, user/sign-out)
- `pages/AnalyticsPage.tsx`: 12-col `max-w-[1800px]` grid, per-tab composition, per-tab queries
- `components/FilterBar.tsx`: single-row sticky + removable active-filter chips
- `components/KpiCards.tsx`, `PeaksCards.tsx`, `TimelineChart.tsx`, `HeatMap.tsx`/`MapLegend.tsx` (overlay legend, fill height), `AreaPanel.tsx` (side column instead of overlay), `RankingsPanel.tsx` (25 rows, paging, extra cols), `MatrixTable.tsx` (row/col % toggle, mohafaza variant)
- **new** `components/charts/*`: Donut, SmallMultiples, PeriodComparison, Pareto, WeeklyCazaArea, CazaRankTable, HourHeatmap, CoverageCalendar, CsvButton
- **new** `components/tabs/{Overview,Map,Incidents,Casualties,Air,Quality}Tab.tsx`
- `hooks.ts`/`api.ts`/`types.ts`: `useAnalyticsOverview|Map|Incidents|Casualties|Air|Quality`
- `design-system/war-news-analytics/pages/analytics.md`: updated layout spec

Backend (`app/analytics/`)
- `repositories/analytics_repository.py`: new aggregate queries (newly-targeted villages, pareto, weekly caza, war-month, casualty incidents, hour reported, channel, verification-reason categories, quality flags, air by caza/type)
- `services/analytics_service.py`: `get_tab(tab, flt)` builders + fixes 7a/7b/7c
- **new** `services/verification_reason_categories.py`: free-text → category prefixes
- `api/analytics_router.py`: `GET /api/analytics/tab/{overview|map|incidents|casualties|air|quality}`
- `models/facts.py` + `incident_fact_builder.py` + **new** Alembic migration (casualty_explicit / casualty_count_missing), generated, **not run**
- `tests/analytics/test_tabs.py`: filters applied, totals add up, empty period → zeros, KPI == matrix + excluded

Not buildable as specified (data doesn't exist)
- True *time-of-event* heatmap: only *time reported* exists. It will be shown as "hour reported", labelled as such.
- Source breakdown by `incidents.source_id`: single value. Uses `raw_messages.source_name` (channel) instead.
- War months before August 2026: no incidents in this DB.
