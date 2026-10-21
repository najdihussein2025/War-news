# Analytics page: Step 1 recon report

Read-only pass. Only this file was created. No source, migration or data was touched.

## 0. How this report was produced (read first)

This run happened in a cloud container, not on your Windows dev machine. Consequences:

| Item | Status |
|---|---|
| Code reading (models, services, routers, frontend, migrations) | **Done**, with file paths and line numbers |
| `docker compose exec db psql ...` SELECTs (every "count per ..." item) | **NOT RUN.** No Docker daemon and no Postgres in the container |
| `docker compose exec backend alembic heads` | **NOT RUN.** Heads were computed statically from the migration files instead (item 18) |
| `frontend/public/geo/*.geojson` (item 1, 3, 4, 5) | **NOT RUN.** The three files are not in the repo. `frontend/public/geo/` does not exist, and no `.geojson` exists anywhere in the tree. They were probably never committed or pushed |
| Anything measurable from `Data/Villages.json` (the seed file for `villages`) | Done, labelled "seed file", not "live DB" |

Every unrun item has a ready-to-paste PowerShell/SQL block marked **RUN LOCALLY**. Paste the outputs back or into this file's sections.

Contradictions between the prompt and the code (trusting the code):

1. There is no `backend/` folder. The Python app is at the repo root: `app/`, `alembic/`, `scripts/`, `Data/`. The frontend is `frontend/`.
2. Routers are not inside each domain. They live in `app/api/*_router.py` and are registered in `app/api/router.py`.
3. There is no `frontend/src/mocks/` folder.
4. `Conditions.json` has **45** rows, not 44. Migration `20260924_0062` additionally inserts a 46th-style row "Unclassified / Needs Review" (see item 6).
5. Output path: repo already has `Docs/` (capital D). I used `Docs/analytics/` to avoid a case clash on Windows. Move it if you want lowercase.
6. The `villages` table has **no lat/lon**. `coord_x`/`coord_y` are UTM zone 36N metres (item 2).

---

## A. Map file to village join

### 1. lb_village.geojson
**NOT RUN, file absent.** RUN LOCALLY after adding the files:

```powershell
$g = Get-Content frontend\public\geo\lb_village.geojson -Raw -Encoding UTF8 | ConvertFrom-Json
$g.features.Count
($g.features | Select-Object -First 3 | ForEach-Object { $_.properties } | ConvertTo-Json -Depth 3)
(Get-Item frontend\public\geo\*.geojson | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,2)}})
```

Also record file size: a 1,610-polygon village layer may be several MB and will need simplification for the browser.

### 2. `villages` model and table
`app/news/models/village.py:9-33`, table `villages`:

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK autoincrement | no | FK target for incidents / air_violations |
| `acs_code` | **Integer**, unique | no | ACS (Central Administration of Statistics) code, always 5 digits in seed (10110 to 74183) |
| `acs_name` | String | yes | |
| `cad_name` | String | yes | cadastral name |
| `ref_name_en` | String | yes | |
| `ref_name_ar` | String | yes | |
| `caza_en`, `caza_ar` | String | yes | free text, no code column |
| `mohafaza_en`, `mohafaza_ar` | String | yes | free text, no code column |
| `coord_x`, `coord_y` | Float | yes | **UTM 36N metres** (x 698,790 to 824,056; y 3,660,600 to 3,842,092 in seed). Converted to lat/lon by `utm36n_to_wgs84()` at `app/news/repositories/map_event_repository.py:12` |
| `is_active` | Boolean, default true | no | |
| `created_at` | timestamptz | no | |

Seed file facts (`Data/Villages.json`, loaded by `app/core/seeds/seed_villages.py`):
- 1,560 rows, **1,544 unique `acs_code`**. 16 codes appear twice with identical names (e.g. 63274 Anane, 34249 Basbina, 51117 Zahle Er-Rassiyé). The seeder skips the duplicates, so the seed yields at most 1,544 villages. The live table may have more if villages were added later (see `scripts/find_missing_lebanon_villages.py`, `Data/missing_village_candidates.csv`).
- 1,610 geojson villages vs at most about 1,544 seeded means **at least 66 geojson polygons will have no village row** unless the live table was extended.

> **Key risk for the join (cannot be settled without the file):** `acs_code` is the ACS statistical code. The OCHA/HDX layer's village `code` may be a different code system (cadastral or HDX p-code). Both being 5-digit numeric strings is not proof they are the same system. Item 3 decides this.

### 3. Join measurement
**NOT RUN.** RUN LOCALLY (script stays outside the repo, nothing is written to the DB):

```powershell
# 1. export villages (SELECT only)
docker compose exec db psql -U WAR_USER -d war_news_dev -A -F "|" -t -c "SELECT id, acs_code, ref_name_ar, ref_name_en, caza_en FROM villages" | Out-File $env:TEMP\villages.txt -Encoding utf8
```
```python
# %TEMP%\join_check.py  (outside the repo)
import json, random
g = json.load(open(r"frontend/public/geo/lb_village.geojson", encoding="utf-8"))
feats = {str(f["properties"]["code"]): f["properties"] for f in g["features"]}
rows = [l.strip().split("|") for l in open(r"%TEMP%/villages.txt", encoding="utf-8") if l.strip()]
v = {r[1]: r for r in rows}                       # acs_code as text
print("geojson features:", len(feats), "villages:", len(v))
m = set(v) & set(feats)
print("match exact (text):", len(m), " (int):", len({int(x) for x in v} & {int(x) for x in feats}))
print("villages w/o geojson:", len(set(v) - set(feats)))
for c in sorted(set(v) - set(feats))[:40]: print(v[c])
print("geojson w/o village:", len(set(feats) - set(v)))
for c in sorted(set(feats) - set(v))[:15]: print(c, feats[c]["name_en"], feats[c]["name_ar"])
for c in random.sample(sorted(m), 20): print(c, "|", v[c][2], v[c][3], "<->", feats[c]["name_ar"], feats[c]["name_en"])
```

Decision rule: if exact match is at least 90 percent **and** the 20 sampled pairs are the same place, use `acs_code = code`. Otherwise go to item 4.

### 4. Fallback (name + caza)
**NOT RUN.** Normalisation to reuse: `app/core/text_normalization.py::normalize_arabic_text` (already used by `breach_counting_service._normalized_name`). The fallback key would be `(normalize_arabic_text(ref_name_ar), caza_code)` against geojson `(normalize_arabic_text(name_ar), caza_code)`. Known risk from the seed file: names repeat inside a caza ("Kfar Tay El-Matn" and "Kfar Tay Kesrouane" are different places; `scripts/audit_village_name_collisions.py` and `scripts/report_village_key_collisions.py` already exist for this). Measure after item 3, only if exact match is under 90 percent.

### 5. Caza and mohafaza naming
Geojson side: **NOT RUN.** Our side, from the seed file (live table may differ, verify with the SQL below).

Our mohafazat (8, Akkar and Baalbek-Hermel already split out, matching the 2024 HDX structure):

| mohafaza_en | mohafaza_ar | villages in seed |
|---|---|---|
| Beirut | بيروت | 13 |
| Mount Lebanon | جبل لبنان | 512 |
| North | الشمال | 266 |
| Akkar | عكار | 165 |
| Baalbek_Hermel | بعلبك - الهرمل | 94 |
| Bekaa | البقاع | 134 |
| South | الجنوب | 230 |
| Nabatiye | النبطية | 146 |

Our cazas (26) and their mohafaza. The `geojson caza_code` column must be filled in locally:

| villages.caza_en | caza_ar | mohafaza_en | villages | geojson caza_code |
|---|---|---|---|---|
| Akkar | عكار | Akkar | 165 | ? |
| Aley | عاليه | Mount Lebanon | 75 | ? |
| Baabda | بعبدا | Mount Lebanon | 57 | ? |
| Baalbek | بعلبك | Baalbek_Hermel | 85 | ? |
| Batroun | البترون | North | 74 | ? |
| Bcharre | بشري | North | 24 | ? |
| Beirut | بيروت | Beirut | 13 | ? |
| Bint Jubail | بنت جبيل | Nabatiye | 38 | ? |
| Chouf | الشوف | Mount Lebanon | 100 | ? |
| El Metn | المتن | Mount Lebanon | 101 | ? |
| Hasbaiya | حاصبيا | Nabatiye | 23 | ? |
| Hermel | الهرمل | Baalbek_Hermel | 9 | ? |
| Jezzine | جزين | South | 77 | ? |
| Jubail | جبيل | Mount Lebanon | 99 | ? |
| Kasrouane | كسروان | Mount Lebanon | 80 | ? |
| Koura | الكورة | North | 43 | ? |
| Marjaayoun | مرجعيون | Nabatiye | 33 | ? |
| Minieh-Danieh | المنية الضنية | North | 57 | ? |
| Nabatiye | النبطية | Nabatiye | 52 | ? |
| Rachiaya | راشيا | Bekaa | 30 | ? |
| Saida | صيدا | South | 78 | ? |
| Sour | صور | South | 75 | ? |
| Tripoli | طرابلس | North | 16 | ? |
| West Bekaa | البقاع الغربي | Bekaa | 41 | ? |
| Zahle | زحلة | Bekaa | 63 | ? |
| Zgharta | زغرتا | North | 52 | ? |

Naming flags found in code (no geojson needed):
- **Spelling drift inside our own code.** `app/news/constants/air_violation_conditions.py:CAZA_TO_MOHAFAZA` uses `Hasbaya` and also has a `Zahrani` key. `villages` uses `Hasbaiya` and has no Zahrani caza (Lebanon has 26 cazas; Zahrani is not one of them, so that key looks stale). `caza_alias_resolver.canonicalize_caza` bridges these, which is why the breach service works; any new code must go through it or through a code mapping, never string equality.
- Mohafaza spelling `Baalbek_Hermel` (underscore) is a stored value, not a display name.
- "Akkar" is both a caza and a mohafaza name, so a name-only join between levels is ambiguous. Always join on codes.
- Caza count in our data is 26, matching the expected HDX 26. Confirm 1:1 locally; expect the Hasbaiya/Hasbaya, Bint Jubail/Bint Jbeil, Jubail/Byblos, El Metn/Matn, Kasrouane/Keserwan style differences, so the mapping table must be explicit (stored in `admin_areas`, not computed).

RUN LOCALLY to confirm live values:
```powershell
docker compose exec db psql -U WAR_USER -d war_news_dev -c "SELECT mohafaza_en, caza_en, caza_ar, count(*) FROM villages GROUP BY 1,2,3 ORDER BY 1,2"
docker compose exec db psql -U WAR_USER -d war_news_dev -c "SELECT count(*) total, count(DISTINCT acs_code) FROM villages"
```
```powershell
# geojson caza list
$c = Get-Content frontend\public\geo\lb_caza.geojson -Raw -Encoding UTF8 | ConvertFrom-Json
$c.features | ForEach-Object { $_.properties } | Select-Object code,name_en,name_ar,mohafaza_code | Format-Table
```

---

## B. Actions

### 6. `conditions`
Model `app/news/models/condition.py`: `id` Integer PK, `action_en`, `action_ar` (unique), `note` Text, `is_active`, `created_at`. **No category/type column.** Seeded from `Data/Conditions.json` (`app/core/seeds/seed_conditions.py`, ids by insertion order, JSON rows have no `id`).

Ids below are the JSON order (= expected ids 1..45 on a fresh seed). **Verify against the live DB**, see the discrepancy flagged under the table.

| id | action_en | action_ar | proposed family | air viol. |
|---|---|---|---|---|
| 1 | Bombs | قصف وغارات | airstrikes | |
| 2 | Warning Raid | غارة تحذيرية | airstrikes | |
| 3 | Drone Failure | سقوط مسيّرة | drone strikes | |
| 4 | Suicide Drone | مسيرة مفخخة | drone strikes | |
| 5 | Artillery Shelling | قصف مدفعي | artillery shelling | |
| 6 | Tank Fire | قذائف الدبابات | artillery shelling | |
| 7 | Phosphorus Bombs | قذائف فوسفورية | flares / phosphorus | |
| 8 | Smoke Grenades | قنابل دخانية | flares / phosphorus | |
| 9 | Flare Bomb | قنابل مضيئة وحارقة | flares / phosphorus | |
| 10 | Sound Bombs | قنابل صوتية | flares / phosphorus | |
| 11 | Cluster Bombs | قنابل عنقودية | airstrikes | |
| 12 | Nail bombs | قنابل مسمارية | artillery shelling | |
| 13 | Grenades | قنابل | gunfire and small arms | |
| 14 | Fissile Shells | قذائف انشطارية | artillery shelling | |
| 15 | Decoy Flares | القاء بالونات حرارية | flares / phosphorus | |
| 16 | Hand Grenades | قنابل يدوية | gunfire and small arms | |
| 17 | Shooting | إطلاق نار | gunfire and small arms | |
| 18 | Sweeping Operations | عملية تمشيط | incursions | |
| 19 | Aerial Sweep | عملية تمشيط مروحي | incursions | |
| 20 | Ground Incursion | توغل بري | incursions | |
| 21 | Mining & Detonation | تلغيم وتفجير | demolitions | |
| 22 | Stationing | تمركز | incursions | |
| 23 | Naval Incursion | توغل بحري | incursions | |
| 24 | Road Blockage | قطع طريق | incursions (ground ops) | |
| 25 | Bulldozing | حفر وجرف | demolitions | |
| 26 | Cutting Trees | قطع اشجار | demolitions | |
| 27 | Burning Properties | احراق ممتلكات | demolitions | |
| 28 | Raiding & Stealing Homes | اقتحام/ سرقة منازل | incursions | |
| 29 | Arrest Operation | عملية احتجاز | incursions | |
| 30 | Kidnapping | خطف | incursions | |
| 31 | Ambushes | كمائن | gunfire and small arms | |
| 32 | Releasing Cattle | تسريح ماشية | other | |
| 33 | Installing Surveillance Devices | اجهزة تجسس | other | |
| **34** | Spy Balloon | منطاد تجسسي | air violations | **yes** |
| **35** | Warplane | طيران حربي | air violations | **yes** |
| **36** | Surveillance Aircraft | طيران استطلاعي | air violations | **yes** |
| 37 | Supersonic boom | خرق جدار الصوت | air violations (candidate, see note) | no |
| **38** | Helicopter Hovering | طيران مروحي | air violations | **yes** |
| 39 | Feigned Attacks | غارات وهمية | other | |
| 40 | Interceptor Missile | صاروخ اعتراضي | other | |
| 41 | Unexploded Shells | قذائف لم تنفجر | other | |
| 42 | Throwing Foreign Objects / Substances | رمي أجسام/ مواد مجهولة | other | |
| 43 | Broadcast Provocative Statements / Warning Messages | عبارات / مناشير تحريضية / اتصالات تحذيرية | other | |
| 44 | Obstructing Duties | عرقلة مهام | other | |
| 45 | Vehicle Movement (JSON) | تحرك آليات | incursions | no |

Confirmed in code: air-violation ids are exactly **{34, 35, 36, 38}** (`app/news/constants/air_violation_conditions.py:8-18`, `AIR_VIOLATION_CONDITION_IDS`).

**Discrepancy to resolve:** code treats **condition 45** as the "Unclassified / Needs Review" bucket (`incident_materialization_service.py:1380`, `summaries/intake_service.py:137`; the constants file comments it as a Red Alert fallback). But `Conditions.json` row 45 is "Vehicle Movement", and migration `20260924_0062` upserts "Unclassified / Needs Review" by `action_ar` without a fixed id. So on a given DB id 45 is either one or the other, or Unclassified is 46. Check before building `action_families`:

```powershell
docker compose exec db psql -U WAR_USER -d war_news_dev -c "SELECT id, action_en, action_ar, is_active FROM conditions ORDER BY id"
```

Rule for `action_families`: key it by `condition_id` rows in a table (not by hard-coded ids in code), include "Unclassified" in an `unclassified` family, and give 37 (supersonic boom) an explicit decision. It is a CNRS air-related condition but is **not** in the breach-counting set, so as an incident it would count as an incident, not a breach. Suggested 9 families: airstrikes, drone strikes, artillery shelling, flares/phosphorus, demolitions, gunfire/small arms, incursions, air violations, other (plus unclassified).

---

## C. Incidents: what the facts table will read

### 7. Incident fields
`app/news/models/incident.py` (table `incidents`), `incident_details.py`, `incident_update.py`, `bulletin_casualty_group.py`.

| Need | Where | Type |
|---|---|---|
| event date | `incidents.event_date` | `date`, NOT NULL |
| event time | `incidents.event_time` | `time`, nullable |
| `event_month` | `incidents.event_month` | String (legacy label) |
| created / updated | `incidents.created_at`, `incidents.updated_at` | timestamptz; `updated_at` has `onupdate=func.now()` |
| optimistic lock | `incidents.version` | Integer, `version_id_col` (bumps on every ORM UPDATE of the row) |
| village | `incidents.village_id` | Integer FK `villages.id` RESTRICT, **nullable**, **one village per incident**. Also `village_display_name` String |
| condition | `incidents.condition_id` | Integer FK `conditions.id` RESTRICT, **nullable** |
| source / channel | `incidents.source_id` (BigInt FK `sources.id` SET NULL), `raw_message_id` (FK `raw_messages.id`), `source_link`, `source_link_2` | |
| origin | `incidents.origin` enum `live` / `summary` | |

**One village per incident.** There is no per-village child table for incidents. A message naming several villages becomes several incidents. Their shared toll is tracked by `bulletin_casualty_groups` (+ `bulletin_casualty_group_members`, one row per village with `incident_id`, `ordinal`; `ordinal 0` is the owner):
- `casualty_scope` enum: `per_village_exact`, `bulletin_aggregate`, `unspecified`
- `village_ids` JSONB in first-mention order, `owner_village_id`, `owner_incident_id`
- **The full shared toll lives on the owner incident only; member incidents keep NULL casualties** (comment at `bulletin_casualty_group.py:68-69`). So summing `incidents.total_deaths` does **not** double count a bulletin aggregate. It does attribute the whole toll to the first-mentioned village.
- Incident-level marker: `incidents.casualty_status` CHECK in (`none_mentioned`, `explicit_none`, `exact`, `count_missing`, `aggregate_only`). `aggregate_only` = shared total. Also `casualty_deaths_status`, `casualty_injuries_status`, `casualty_status_remaining_total` JSONB, `casualty_is_preliminary` bool.

**Casualty fields:**
- Headline totals: `incidents.total_deaths`, `incidents.total_injuries` (Integer, nullable). This is what the app's KPI uses (`app/news/repositories/reported_casualties.py:reported_casualty_people_expression` = `coalesce(total_deaths,0)+coalesce(total_injuries,0)`).
- Demographic breakdown in `incident_details`: `male_d`, `male_i`, `female_d`, `female_i`, `children_d`, `children_i` (D = deaths, I = injuries). Totals are derived by `category_mapper.py` (around line 773); a breakdown can sum to less than the total (unknown gender), so the facts table should store `unspecified = total - male - female - children` rather than assume they add up. Many other per-category counts exist (`la_*`, `un_*`, `hos*`, `press*`, `car*` ...) and are out of scope for step 2.
- `incidents.deaths`, `incidents.injuries`, `injuries_extra`, `martyrs`, `moh`: legacy Excel-import columns ("meaning unconfirmed"). Do **not** use as headline numbers. Note `casualty_transition_merge.py:89` copies `deaths` into `total_deaths` on some merges.

**"Do not count" signals:**
- `is_deleted = true` (soft delete, `deleted_reason` in `admin`, `duplicate_merge`, `cluster_subsumption`, `summary_superseded`)
- `verification_status = 'rejected'` (the listing code excludes it: `incident_repository_listing.py:62`, `casualty_flag_evaluator.py:45`)
- Open question: `duplicate_flag = true`. Soft delete sets it false, so flagged duplicates that are not deleted are still live rows. Confirm with the count query below.
- Open question: `details_pending = true` (casualty details still being filled). Decide whether to count them (recommend yes, with the later recompute fixing totals).

**Verification status:** `incidents.verification_status` String(24), default `'auto_processed'`. Allowed values (DTO Literal at `app/news/dtos/incident_dto.py:50`): `auto_processed`, `needs_verification`, `verified`, `rejected`. No DB CHECK constraint.

> **Needs your confirmation:** "Headline numbers default to VERIFIED only". By default the pipeline writes `auto_processed`, and `verified` is set only by an admin action (`verification_flags_router.py:369`). If "verified" literally means `verification_status = 'verified'`, the headline could be a small fraction of all incidents. The app already has a "matched" filter meaning `!= needs_verification` (`incident_repository_listing.py:106`). Run the counts below, then pick: (A) `verified` only, (B) `verified + auto_processed` (recommended default; `needs_verification` and `rejected` excluded, `needs_verification` behind the toggle).

RUN LOCALLY:
```powershell
docker compose exec db psql -U WAR_USER -d war_news_dev -c "SELECT verification_status, is_deleted, count(*), sum(coalesce(total_deaths,0)) deaths, sum(coalesce(total_injuries,0)) inj FROM incidents GROUP BY 1,2 ORDER BY 1,2"
docker compose exec db psql -U WAR_USER -d war_news_dev -c "SELECT duplicate_flag, details_pending, is_deleted, count(*) FROM incidents GROUP BY 1,2,3 ORDER BY 1,2,3"
docker compose exec db psql -U WAR_USER -d war_news_dev -c "SELECT casualty_status, count(*) FROM incidents WHERE NOT is_deleted GROUP BY 1"
```

### 8. Row counts
**NOT RUN.** RUN LOCALLY:
```powershell
docker compose exec db psql -U WAR_USER -d war_news_dev -c "SELECT count(*) total, count(*) FILTER (WHERE NOT is_deleted) live, count(*) FILTER (WHERE village_id IS NULL) null_village, count(*) FILTER (WHERE condition_id IS NULL) null_condition, min(event_date), max(event_date) FROM incidents"
docker compose exec db psql -U WAR_USER -d war_news_dev -c "SELECT i.condition_id, c.action_en, count(*) FROM incidents i LEFT JOIN conditions c ON c.id=i.condition_id WHERE NOT i.is_deleted GROUP BY 1,2 ORDER BY 3 DESC LIMIT 15"
docker compose exec db psql -U WAR_USER -d war_news_dev -c "SELECT count(*) FILTER (WHERE event_date IS NULL) FROM incidents"
```
Schema note: `village_id` and `condition_id` are nullable, so facts need a NULL-village bucket (`village_code = NULL`, counted in national totals only) and a NULL-condition bucket.

### 9. Where an incident changes after creation, and the recompute signal

Writers (all in `app/`):
- Create: `incident_repository.py:1017` and `:1779`; `incident_workbook_service.py:345` (Excel import); `incident_materialization_service.py:1240`, `:1360`, `:1797` (live and summary flows).
- Manual edit: `incident_repository.py` (audit rows at `:1144`, `:1210`), `verification_flags_router.py:307`, `:495`.
- Pipeline merge / enrichment: `incident_repository.py:1666`, `:2069`, `:2122`, `:2220`; `merge_detail_fill.py:115`; `tier2_detail_fill_service.py:310-320`, `:513` (sets `total_deaths`); `incident_materialization_service.py:2473`; `bulletin_reconciliation_service.py:302` (changes owner incident toll); `incident_casualty_recompute.py:921`.
- Status change (verify / reject / restore): `incident_repository.py:1265`, `:1302`, `:1419`, `:1694`; `rejected_news_router.py:380`; `rejected_incidents_router.py:40`; `verification_flags_router.py:369`, `:521`; `incident_verification_flag_repository.py:230`.
- Delete: `soft_delete.py:soft_delete_incident` (the one soft-delete boundary), `incident_repository.py:2779`.
- Detail-only edits (casualty demographics): `incident_detail_edit_service.py:359-383` recomputes totals; this changes `incident_details`.

Candidate signals, and why each is not enough alone:

| Signal | Catches | Misses |
|---|---|---|
| `incidents.updated_at` | any UPDATE of the `incidents` row via ORM/Core (`onupdate`) | edits that change only `incident_details` rows; raw SQL scripts in `scripts/` that do not set it; hard deletes; the old `event_date` when a date is edited (you only see the new one) |
| `incident_updates` rows | audited edits | Several writers bypass the audited writer `record_incident_change` and insert `IncidentUpdate(...)` directly (`verification_flags_router.py:307`, `incident_casualty_recompute.py:921`), and scripts/backfills write nothing. Not a complete log |
| Service-layer hook | what it is wired into | easy to miss one of the 30+ write sites above; future code forgets |

**Recommendation: database trigger into a dirty-date queue** (single signal that cannot be bypassed):
- Table `analytics_dirty_dates(event_date date PK, marked_at timestamptz)` (plus an `area`/`scope` is not needed; facts are keyed by date).
- AFTER INSERT/UPDATE/DELETE trigger on `incidents` marks `OLD.event_date` and `NEW.event_date` (covers date edits). Same trigger on `incident_details` (resolve the date through `incident_id`). Same on `air_violations` / `air_violation_locations` and on `bulletin_casualty_groups` / members.
- Worker loop: pick dirty dates, delete+rebuild only those dates' **live** fact rows in one transaction, then clear the marks only if `marked_at` has not moved since the read.
- Air-violation breaches use anchored windows that can span midnight, so mark `date +/- 1` for air violation changes.
- Changes to `action_families` or `admin_areas` mappings trigger a full rebuild, not a dirty date.
- Fallback if you dislike triggers: ORM `after_flush` event on `Incident`/`IncidentDetail` writing the dirty date. Cheaper to write, but misses raw SQL and scripts.

---

## D. Air violations

### 10. Breach counting
`app/news/services/air_violations/breach_counting_service.py` (pure; dataclasses in, dataclasses out). Only importer: `app/news/repositories/air_violation_repository.py:41` (the repository builds `BreachReport` objects at `:320`).

Public functions:
- `compute_breaches(reports: Iterable[BreachReport], *, warplane_window=None, drone_long_window=None) -> list[AirViolationBreach]` (line 263)
- `count_breaches_by_condition(breaches) -> dict[int,int]` (line 318; keys 34, 35, 36, 38)
- helpers: `expand_report_units`, `breach_window_minutes`, `event_datetime`, `village_key`
- Inputs: `BreachReport(id, condition_id, event_date, event_time, caza_en, caza_ar, villages: tuple[BreachVillage(village_id, name, caza_*, mohafaza_*)])`.
- Output: `AirViolationBreach(id, condition_id, unit_type, unit_key, unit_en, unit_ar, window_start, window_end, report_ids, villages, window_minutes, needs_review)`.
- Windows come from `settings.air_violation_warplane_window_minutes` (default 10, `app/core/config.py:18`) and a drone long window setting.

**Geography is intrinsic to the condition, not selectable:**

| Condition | Counting unit | Window |
|---|---|---|
| 35 Warplane | **mohafaza** (a report naming several mohafazat counts in each) | anchored 10 min |
| 36 Drone / surveillance | **caza** | anchored 6 h in `DRONE_SIX_HOUR_CAZAS` (10 cazas), otherwise once per Beirut calendar day |
| 38 Helicopter | **village** (once per village named) | none |
| 34 Spy balloon | **caza** (once per caza named) | none |

Consequences for the heat map:
- The natural heat-map level per air-violation action: warplane = mohafaza only; drone and balloon = caza (roll up to mohafaza); helicopter = village (rolls up to caza and mohafaza). A village-level map for warplane or drone cannot be produced from the breach rules; the UI must grey out or fall back for those actions.
- Summing breaches across units can exceed the national headline (one report naming 2 mohafazat counts twice). The national headline must be computed on its own, not summed from areas.
- A breach unit with no resolvable location is emitted under the unit `Unknown` with `needs_review=True`; the facts table needs an "unknown area" bucket.
- Unit keys are English strings from `canonicalize_caza` (`caza_alias_resolver.py`) and village `mohafaza_en` spellings. Map them to `admin_areas.code` through the same canonicaliser.
- A breach is dated by `window_start`. The facts date for a breach = `window_start.date()`.
- Breach counts are computed over all reports at once (windows need neighbours). The worker must rebuild air-violation facts per affected date range, not per row.

Location storage on `air_violations` (`app/news/models/air_violation.py`): `village_id` (nullable, legacy single), `caza_en`/`caza_ar` strings, `event_month`, `war_month`, and **`air_violation_locations`** rows (`air_violation_id`, `village_id`, `raw_location_text`) for multiple villages per report. So location is "caza text plus zero or more villages", never mohafaza directly.

### 11. air_violations row counts
**NOT RUN.** RUN LOCALLY:
```powershell
docker compose exec db psql -U WAR_USER -d war_news_dev -c "SELECT condition_id, count(*), min(event_date), max(event_date), count(*) FILTER (WHERE village_id IS NULL) no_village, count(*) FILTER (WHERE caza_en IS NULL) no_caza FROM air_violations GROUP BY 1 ORDER BY 1"
docker compose exec db psql -U WAR_USER -d war_news_dev -c "SELECT review_status, count(*) FROM air_violations GROUP BY 1"
docker compose exec db psql -U WAR_USER -d war_news_dev -c "SELECT count(DISTINCT air_violation_id) FROM air_violation_locations"
```
Note `review_status`/`review_reason` exist on `air_violations`; decide whether rows pending review count (see `air_violation_exclusions.py`, `air_violation_eligibility.py`; read these before step 2 to learn which rows the existing Air Violations page excludes, and reuse that predicate).

---

## E. Archive plan

### 12. Existing export/archive code
- `app/export/` is an **empty scaffold** (only `__init__.py` files). No incident export service exists.
- `IncidentWorkbookService` (`app/news/services/incidents/incident_workbook_service.py:257`) is import only (xlsx -> incidents). It resolves village by **ACS code** (`_resolve_village_id`, `:459`), condition by **action text** (`_conditions_by_action`, `:428`), source by name.
- Migration `20260903_0050` creates DB view **`incident_excel_view`** shaped like the legacy workbook. It carries `ACS_Code`, `Action_E/A`, names, date/time, deaths/injuries, the detail columns, note, MOH, worker name, links. It does **not** carry: incident `id`, `village_id`, `condition_id`, `verification_status`, `is_deleted`, `casualty_status`, `casualty_scope` / bulletin group, `origin`, `source_id`. (Village and condition can be re-linked through ACS code and action text, but verification status and the shared-toll marker would be lost.)
- `scripts/export_today_webhook.py` exports raw webhook messages to CSV, unrelated.
- FKs `incidents.village_id` and `condition_id` are `RESTRICT`, so villages and conditions cannot be deleted while incidents exist. After a reset nothing blocks keeping a copy.

Options:

| | (a) `incidents_archive` table in Postgres | (b) build facts from rows, then freeze |
|---|---|---|
| Fidelity | Lossless: all columns, can re-derive any future metric (new families, new geography, per-incident rankings) | Lossless only for the chosen grain (date x village x condition x status); no per-incident drill-down or "most deaths in one incident" |
| Risk | One extra table to maintain; schema drift if `incidents` changes | Frozen numbers cannot be corrected if a mapping bug is found later |
| Reset safety | Copy in the same transaction before the delete | Must run the full backfill before the reset or history is gone |

**Recommendation: do both, in this order.** (1) In one transaction, `CREATE TABLE incidents_archive AS` a snapshot of `incidents` joined to the needed `incident_details` casualty columns (`male_d`, `male_i`, `female_d`, `female_i`, `children_d`, `children_i`) plus the bulletin group id/scope. Keep `id`, `village_id`, `condition_id`, `verification_status`, `is_deleted`, `casualty_status`, `event_date`. Drop the embedding column (large, not needed). Keep the Excel export as the human-readable copy. (2) Build `analytics_daily_facts` from `incidents_archive` + live rows, tagging archive-sourced rows `source = 'archive'`.

Two traps to design in now:
- **The incremental worker must never delete `source='archive'` fact rows.** Otherwise the first time a past date is marked dirty the rebuild finds no live incidents and wipes history.
- **The dirty-date trigger fires on the reset's mass DELETE.** Disable it for the reset (or truncate with the trigger off) so thousands of dates are not queued for a rebuild that would find nothing.

Also record the archive date so the UI can say "archive + live" on the first part of the timeline.

---

## F. Existing patterns to reuse

### 13. Backend domain layout and route protection
Domain folders are `app/<domain>/{actions,dtos,interfaces,models,repositories,services}` (+ `__init__.py` in each), e.g. `app/sources/`:

```
app/sources/
  actions/      ingest_source_action.py, list_sources_action.py ...
  dtos/         source_dto.py, webhook_dto.py ...
  interfaces/   source_repository_interface.py ...
  models/       source.py, content_source_block.py ...
  repositories/ source_repository.py ...
  services/     cnrs_source.py, red_alert_collector.py ...
```
`app/news/` follows the same layout and adds `constants/`. **Routers are not inside the domain.** They live in `app/api/<name>_router.py`, e.g. `app/api/map_router.py` (`APIRouter(prefix="/api/map", tags=["map"])`), included in `app/api/router.py`. So the new domain is `app/analytics/{actions,dtos,interfaces,models,repositories,services}/` plus `app/api/analytics_router.py` plus one `include_router` line. Models must be imported in `alembic/env.py` (it imports `app.accounts.models`, `app.logs.models`, `app.news.models`, `app.sources.models`) and in `app/analytics/models/__init__.py`, or autogenerate will not see them.

Route protection (`app/api/deps.py`):
```python
require_admin = require_roles(RoleName.admin, RoleName.super_admin)   # admin + super_admin
require_super_admin = require_roles(RoleName.super_admin)
# usage in every router:
_current_user: User = Depends(require_admin)
```
Auth is a cookie `access_token` or Bearer token checked against `auth_sessions`.

### 14. Background workers
Workers are separate docker-compose services in `docker-compose.yml` that loop a script:
```yaml
bulletin-reconciliation-worker:
  environment: { PIPELINE_ROLE: bulletin-reconciliation-worker, PG_APPLICATION_NAME: ... }
  command: sh -c "while true; do python -m scripts.bulletin_reconciliation_sweep; sleep ${BULLETIN_RECONCILIATION_SWEEP_INTERVAL_SECONDS:-1800}; done"
```
Others: `live-sweep-worker` (300 s), `backlog-relevance-worker` (1800 s), `summary-reconcile-worker` (300 s), `cnrs-poll-worker` (300 s), `pipeline-worker` (`python -m app.core.scripts.run_pipeline_worker`), a Red Alert collector service. Reporting convention (`scripts/bulletin_reconciliation_sweep.py:25-32`): one summary line `processed=N succeeded=N failed=N`, written to the logger **and** `print(..., flush=True)`, exit code `0 if failed == 0 else 1`. There is also an in-process APScheduler (`app/core/scheduler.py`) used only for the Red Alert loop. The analytics refresh should copy the `scripts/*_sweep.py` + compose-loop pattern, with its interval in config.

### 15. Caching
Redis is in use (`redis>=5`, service `redis:7-alpine` in compose, `settings.redis_url`, `settings.cache_enabled`). Helpers in `app/core/cache.py`: `get_json`, `set_json(key, value, ttl)`, `delete_keys`, `get_cache_version`, `increment`; all fail open (log a warning and return `None`). Used by `news_router.py` (15 s TTL with a version key), `conditions_router.py`, `villages_router.py` (`reference:villages:v1`, 1 h). Analytics responses can use `set_json` with a version key bumped by the refresh worker.

### 16. Frontend
- Stack: React 19, react-router-dom 7, TanStack Query 5, Zustand 5, axios, Tailwind 3, Vite 8, vitest. **No chart library and no map library is installed** (`package.json` has none of d3, leaflet, maplibre, recharts, echarts). The heat map needs a new dependency. Lightest fit for a choropleth from static GeoJSON without tiles: `d3-geo` + `d3-scale` rendering SVG/Canvas; add a charting lib only if the timelines need it.
- Router: `src/app/routes.tsx`, `createRoutes()` has **two duplicated trees**, `/admin/*` (role `admin`) and `/superadmin/*` (role `super_admin`), each wrapped in `RequireRole` + `AppShell`. A new page needs a route entry in **both** trees (e.g. `{ path: "analytics", element: <AnalyticsPage /> }`). Both roles are allowed, which matches the requirement.
- Sidebar: `navItems` array in `src/app/AppShell.tsx:147` (`label`, `path`, `icon`, `hiddenFrom: Role[]`); page titles from `pageMeta` (`AppShell.tsx:205`). Add an item with `hiddenFrom: []` and a `pageMeta` entry (match order matters: more specific first).
- Feature layout: `src/features/<name>/{api.ts,hooks.ts,types.ts,pages/}` (see `airViolations`, `map`). `src/features/map/` has only `api.ts`/`types.ts` (the old map page now redirects to the dashboard).
- **Mocks: `src/mocks/` does not exist.** There is no mock layer in the repo. If step 2 wants mock data for the UI, create it fresh (or use MSW). Note it, don't assume the pattern.
- Primitives: `src/components/StatusBadge.tsx` (`label`, `variant`), `src/components/Table.tsx`, `src/components/ui/DataTable.tsx`, plus `ui/{Card,Dialog,EmptyState,Select,Input,Button,ConfirmDialog,...}`. `formatRelativeTime` is in `src/lib/formatters.ts:31` (also `formatDate`, `formatDateTime`, `formatTimeGap`).
- i18n / RTL: **no i18n library**; UI text is hard-coded English, `index.html` is `lang="en"`. Arabic is handled per element with `dir="rtl" lang="ar"` or `dir="auto"` (see `IncidentsPage.tsx:353`, `:389`, `:405`). For the map tooltips show name_en and name_ar with that same per-element approach.
- Public assets: `frontend/public/` has logos only; `geo/` must be created and the geojson committed.

### 17. Settings convention
Confirmed. `app/core/config.py` has `class Settings(BaseSettings)` with defaults inline (e.g. `air_violation_warplane_window_minutes: int = 10` at line 18, `redis_url` at 216, `cache_enabled` at 217). Add analytics tuning there (refresh interval, cache TTL, rebuild batch size, default status filter). Compose passes them as env vars.

### 18. Alembic heads
`docker compose exec backend alembic heads` **NOT RUN.** Computed statically from `alembic/migration/*.py` (88 revisions, parsed `revision` / `down_revision` including the multi-line merge tuples): **exactly one head, `20261019_0081`** (`20261019_0081_fix_drone_helicopter_classification.py`, down_revision `20261019_0080`). A merge migration `2eccf58599e6_merge_heads` exists from earlier. Config: `alembic.ini` has `version_locations = %(here)s/alembic/migration`; new migrations go in `alembic/migration/` with `down_revision = "20261019_0081"`. Confirm locally:
```powershell
docker compose exec backend alembic heads
docker compose exec backend alembic current
```
Note: migration `20260903_0050` imports from `incident_workbook_service`, so migrations here depend on app code; keep new analytics migrations self-contained.

---

## Blocking issues (stop step 2 until resolved)

1. **The three geojson files are not in the repo.** Commit them to `frontend/public/geo/`, then run items 1 to 5. The village join (and whether `acs_code` equals the HDX `code` at all) is unmeasured.
2. **No live DB numbers.** Run the SQL blocks in 5, 6, 7, 8, 11. In particular: the exact `verification_status` distribution (the "verified only" headline may be tiny), and the id of the Unclassified condition (45 vs 46).
3. **Define "verified".** Pick (A) `verified` only or (B) `verified + auto_processed` as the headline set, after seeing the counts.
4. **Air-violation geography.** Breaches are natively mohafaza (warplane), caza (drone, balloon) or village (helicopter). The "three levels x any action" map cannot be literally true for air violations. Decide the UI rule (grey out unsupported levels, or roll up only).
5. **Archive before reset is a hard dependency.** Nothing exists today that preserves village id, condition id, verification status and casualties (the Excel view loses status and ids). Step 2 must include the archive step before any data reset.

## Recommended decisions

| Decision | Recommendation |
|---|---|
| Village join method | Exact `acs_code` = geojson `code` (cast both to int) **if** item 3 shows at least 90 percent match and sampled names agree. Store the geojson code in `admin_areas.code` and the link in a new nullable `villages.admin_area_code` filled once by a reviewed script. Fallback to `normalize_arabic_text(name) + caza_code` only for the unmatched remainder, with manual review of ambiguous names. Expect at least 66 geojson polygons with no village row (1,610 vs about 1,544 seeded) |
| Action families table | New table `action_families(id, code, name_en, name_ar, sort)` and `condition_families(condition_id PK, family_id)` as data, not code constants. 9 families: airstrikes, drone strikes, artillery shelling, flares/phosphorus, demolitions, gunfire/small arms, incursions, air violations (34, 35, 36, 38 + decision on 37), other (plus unclassified). Mapping proposed in item 6; verify ids against the live table first |
| Archive option | Both: (a) `incidents_archive` copy in the same transaction as the reset, then (b) facts built from archive + live with `source='archive'` rows that the worker never rewrites. Disable the dirty-date trigger during the reset |
| Recompute signal | Postgres triggers on `incidents`, `incident_details`, `air_violations`, `air_violation_locations`, bulletin groups writing `OLD` and `NEW` `event_date` into `analytics_dirty_dates`; worker rebuilds only `source='live'` rows for those dates (air violations: date +/- 1). `updated_at` and `incident_updates` are each incomplete (item 9) |
| Caza / mohafaza naming source of truth | `admin_areas` (HDX codes) is the single source. `villages.caza_*` / `mohafaza_*` free text and `CAZA_TO_MOHAFAZA` stay as legacy, bridged to codes through one mapping table plus `canonicalize_caza`. Fix `CAZA_TO_MOHAFAZA` (`Hasbaya`, stale `Zahrani`) when touching it. Always join on codes, never on names ("Akkar" is both a caza and a mohafaza) |
| Other | Store `unspecified` casualties (`total` minus male/female/children). Count NULL-village incidents in national totals only. Compute national headline separately from per-area sums (air-violation double counting). Add a coordinate note: `coord_x/y` are UTM 36N, so use `utm36n_to_wgs84` rather than assuming lat/lon; the geojson already carries `center_lat/center_lon` |

---

## Step 1b local recon results (2026-10-21)

### Backup

- Created and validated custom-format backup: `backups/war_news_dev_2026-10-21.dump` (182,569,858 bytes; 174.11 MiB).
- `pg_restore --list` succeeded and included `incidents`, `incident_details`, `incident_updates`, `villages`, `conditions`, `air_violations`, and `raw_messages`.
- `backups/` was already ignored by `.gitignore`; no `.gitignore` change was needed.

### Map files and village join

The three layers were subsequently supplied, verified, committed, and measured; see the completed village-join results below.

### Village join — completed after layers were supplied

The committed files contain 8 mohafaza features, 26 caza features, and 1,610 village features. The live `villages` table has 1,544 rows.

- Exact `villages.acs_code = geojson.properties.code` matches: **1,543** as text and **1,543** as integers.
- Villages without a geojson-code match: **1**. Geojson codes without a village: **67**.
- Duplicate `villages.acs_code` groups: **0** (therefore no duplicate rows to list).
- The Arabic-name-plus-caza fallback, measured only for the unmatched village using the existing Arabic normalisation rules and the code-derived caza mapping, would recover **0** villages.
- Live (not deleted) incidents pointing at a village without a geojson match: **5**.

Full village-without-geojson list:

| id | acs_code | Arabic name | English name | caza |
|---:|---:|---|---|---|
| 419 | 74183 | مزارع شبعا | Chebaa Farms | Hasbaiya |

First 20 geojson codes without a village row:

| code | Arabic name | English name |
|---:|---|---|
| 22001 |  | Litige |
| 22002 |  | Litige |
| 23001 |  | Litige |
| 23002 |  | Litige |
| 23003 |  | Litige |
| 23004 |  | Litige |
| 23005 |  | Litige |
| 23006 |  | Litige |
| 23007 |  | Litige |
| 24001 |  | Litige |
| 24002 |  | Litige |
| 24003 |  | Litige |
| 24004 |  | Litige |
| 24005 |  | Litige |
| 24006 |  | Litige |
| 24007 |  | Litige |
| 24008 |  | Litige |
| 24009 |  | Litige |
| 25001 |  | Litige |
| 25002 |  | Litige |

Twenty random exact-match samples (DB name → GeoJSON name):

| code | DB Arabic / English | GeoJSON Arabic / English |
|---:|---|---|
| 63147 | مكنونية / Maknounet Jezzine | مكنونية / Maknounet Jezzine |
| 36134 | مزرعة بني صعب / Mazraat Bani Saab | مزرعة بني صعب / Mazraat Bani Saab |
| 55174 | مجدل بلهيص / Majdel Balhis | مجدل بلهيص / Majdel Balhis |
| 21456 | قرنايل / Qornayel | قرنايل / Qornayel |
| 37357 | بيت حاويك / Beit Haouik | بيت حاويك / Beit Haouik |
| 53135 | حوش تل صفية / Haouch Tall Safiye | حوش تل صفية / Haouch Tall Safiyeh |
| 35261 | المقيطع / Mqaiteaa | المقيطع / Mqaiteaa |
| 24363 | سلفايا / Selfaya | سلفايا / Selfaya |
| 63261 | جنسنايا / Jensnaya | جنسنايا / Jensnaya |
| 61488 | برتي / Berti | برتي / Berti |
| 62226 | البياض صور / Biyad | البياض صور / Biyad |
| 72277 | ياطر / Yater | ياطر / Yater |
| 32171 | قلحات / Qalhat | قلحات / Qalhat |
| 23544 | عترين / Aathrine | عترين / Aathrine |
| 52151 | خربة قنافار / Khirbet Qanafar | خربة قنافار / Khirbet Qanafar |
| 34144 | كفر عبيدا / Kfar Aabida | كفر عبيدا / Kfar Aabida |
| 52171 | المنصورة / Mansoura BG | المنصورة / Mansoura BG |
| 52217 | كامد اللوز / Kamed El-Laouz | كامد اللوز / Kamed El-Laouz |
| 24349 | مجدليا / Mejdlaiya | مجدليا / Mejdlaiya |
| 22155 | سن الفيل / Sinn El-Fil | سن الفيل / Sinn El-Fil |

Code-derived caza mapping (all 26 live `caza_en` values map to exactly one code; no zero- or multi-code mappings):

| villages.caza_en | villages | geojson caza_code |
|---|---:|---|
| Akkar | 165 | LB51 |
| Aley | 73 | LB31 |
| Baabda | 57 | LB32 |
| Baalbek | 85 | LB21 |
| Batroun | 73 | LB52 |
| Bcharre | 24 | LB53 |
| Beirut | 13 | LB11 |
| Bint Jubail | 38 | LB41 |
| Chouf | 99 | LB33 |
| El Metn | 100 | LB36 |
| Hasbaiya | 23 | LB42 |
| Hermel | 9 | LB22 |
| Jezzine | 76 | LB62 |
| Jubail | 99 | LB34 |
| Kasrouane | 78 | LB35 |
| Koura | 43 | LB54 |
| Marjaayoun | 33 | LB43 |
| Minieh-Danieh | 55 | LB55 |
| Nabatiye | 52 | LB44 |
| Rachiaya | 28 | LB23 |
| Saida | 76 | LB61 |
| Sour | 75 | LB63 |
| Tripoli | 16 | LB56 |
| West Bekaa | 41 | LB24 |
| Zahle | 61 | LB25 |
| Zgharta | 52 | LB57 |

### Incidents

| verification_status | is_deleted | rows | deaths | injuries |
|---|---:|---:|---:|---:|
| auto_processed | false | 2,809 | 235 | 638 |
| auto_processed | true | 278 | 6 | 53 |
| needs_verification | false | 32 | 0 | 0 |
| needs_verification | true | 439 | 0 | 26 |
| rejected | false | 6 | 1 | 2 |
| verified | false | 6 | 0 | 0 |

- Total incidents: 3,570; live: 2,853; NULL village: 0; NULL condition: 0; event-date range: 2026-08-17 to 2026-10-21.
- Deleted or rejected: 723 rows (`is_deleted = true` or `verification_status = 'rejected'`; overlaps counted once).
- Shared-toll marker: `incidents.casualty_status = 'aggregate_only'`; 1 row carries it (and it is the owner-row representation described above).
- Live casualty-status distribution: `aggregate_only` 1, `count_missing` 4, `exact` 12, `explicit_none` 5, `none_mentioned` 1,424, NULL 1,407.

### Conditions and incident use

The live table has 46 condition rows. ID 45 is **Air Activity - Needs Verification** and ID 87 is **Unclassified / Needs Review**; neither is the historical seed-file “Vehicle Movement” assumption. Incident counts by condition are: Artillery Shelling (5) 1,634; Bombs (46) 1,174; Sweeping Operations (18) 199; Mining & Detonation (21) 166; Unclassified / Needs Review (87) 64; Flare Bomb (9) 56; Drone Failure (3) 43; Tank Fire (6) 36; Ground Incursion (20) 23; Burning Properties (27) 21; Warplane (35) 17; Shooting (17) 15; Surveillance Aircraft (36) 10; Grenades (13) 8; Suicide Drone (4) 3; Phosphorus Bombs (7) 3; Aerial Sweep (19) 3; Installing Surveillance Devices (33) 2; Smoke Grenades (8), Cluster Bombs (11), Stationing (22), Naval Incursion (23), Cutting Trees (26), Arrest Operation (29), and Interceptor Missile (40) 1 each; every other condition, including 34, 38, and 45, has 0 incident rows.

### Air violations

| condition_id | rows | date range | has village | caza only | no location |
|---:|---:|---|---:|---:|---:|
| 35 (Warplane) | 173 | 2026-08-14 to 2026-10-21 | 9 | 150 | 14 |
| 36 (Surveillance Aircraft) | 676 | 2026-08-20 to 2026-10-21 | 342 | 318 | 16 |
| 38 (Helicopter Hovering) | 5 | 2026-09-14 to 2026-10-17 | 3 | 1 | 1 |

- `review_status`: NULL 834; `flagged_for_review` 20.
- 354 distinct air-violation IDs have rows in `air_violation_locations`.

### Alembic

`docker compose exec backend alembic heads` returned one head: `20261019_0081`.

### Contradictions found during local recon

1. The agreed headline status mapping is implementable with the live values (`verified` and `auto_processed`), but it currently includes 2,815 live rows, of which only 6 are `verified`; 32 live rows are pending review, 6 live rows are rejected, and 717 rows are deleted. Deleted/rejected exclusions must therefore be explicit in addition to the status filter.
2. The planned code-only village join cannot yet be validated or used because the required geojson layers are absent. This blocks the requested manual-fix list and geo-derived caza/mohafaza mapping.
3. The prior assumption that condition ID 45 was an unclassified bucket is false in the live database: it is `Air Activity - Needs Verification`; the unclassified row is ID 87. Do not hard-code 45.

## Agreed decisions (2026-10-21)

1. Access: the Analytics page lives inside the existing admin panel, for super_admin and admin only. Routes are added to both the /admin and /superadmin trees. No public endpoint.
2. Headline numbers ("counted"): verification_status in (verified, auto_processed) AND not deleted AND not rejected. Rows in needs_verification are shown separately as "pending review" and are excluded from headline totals by default (a toggle can include them). Rejected and deleted rows are never counted. Use the real status values found in Step 4; if names differ, list the mapping. Condition 45 is `Air Activity - Needs Verification` and condition 87 is `Unclassified / Needs Review`; both belong to pending review, not headline totals.
3. History: before the planned data reset, all incidents are copied into a Postgres incidents_archive table that keeps ids, village_id, condition_id, verification status, the shared-toll marker and all casualty fields. Excel stays a human copy only. Fact rows built from the archive are frozen and the refresh worker never rewrites them.
4. Village join: by code only (villages.acs_code to geojson code), never by name. Duplicate acs_codes and unmatched villages go into a manual fix list. Caza and mohafaza for analytics come from the geojson codes, not from name strings (CAZA_TO_MOHAFAZA naming drift such as Hasbaya vs Hasbaiya and the stale Zahrani entry confirms names cannot be trusted).
5. Air violations on the map follow the counting rules:
   - mohafaza level: all air-violation types
   - caza level: drones, spy balloons, helicopters
   - village level: helicopters only
   Unsupported levels are disabled in the UI with a tooltip explaining the rule. Warplane breaches are never split below mohafaza.
6. Recompute signal: database triggers write affected dates to a dirty-dates queue; a worker rebuilds facts for those dates. The data-reset script must disable this trigger while it runs so the mass delete does not queue a full rebuild.
7. Casualty totals: a shared bulletin toll is counted once (it sits only on the first-mentioned village's incident). Analytics shows it as "not attributed to a specific village" where relevant, never spread across villages.

