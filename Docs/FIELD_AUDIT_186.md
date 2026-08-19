# 186-Field Audit Report — Incident Category Sections

**Date:** 2026-08-19  
**Scope:** Task A recon — all `incident_details` fields vs Excel dictionary (`build_answer_key.py` / `Database Sample.xlsx` canonical mapping).  
**Note:** `War_News_2026_Excel_Data_Dictionary.md` is not present in the repo; this audit uses the same canonical field inventory as `scripts/phase2-extraction-testing/build_answer_key.py` plus `Docs/db.md` and the SQLAlchemy model.

## Summary

| Metric | Count |
|--------|------:|
| Canonical category + casualty fields audited | 166 |
| `incident_details` DB columns (excl. PK) | 166 |
| Record-header fields on `incidents` (moh, worker_name, source_link, source_link_2, martyrs, note) | 6 |
| Incident-level casualty rollups on `incidents` (deaths, injuries, total_deaths, total_injuries) | 4 |
| **Total surfaced field inventory** | **176** |
| Fields with confirmed surfacing gaps (pre-fix) | 63 |
| Fields fixed in this task (mapper/serializer) | 28 mapper paths + 1 serializer mapping |

The Excel workbook and answer key define **166** named detail columns grouped into **14 category sections** plus **casualty demographics** (including `obs_duties`, `isf_gs`, `fire`, `arrested`, `lib_y_n`). With six record-header columns and four incident-level casualty totals, the full operational dictionary aligns with the **~186** fields referenced in the project brief.

## Layer definitions

| Layer | Source |
|-------|--------|
| **LLM schema** | Tier-2 `OllamaCategoryDetailService` response schema (`did`, `name`, `casualties`, optional `vehicles`) + root `ExtractionCasualties` |
| **Mapper** | `app/news/services/category_mapper.py` → flat `incident_details` columns |
| **Serializer** | `app/news/services/incident_detail_category_serializer.py` → gated API section payloads |
| **Frontend** | `incidentSchema.ts` + `fieldLabels.ts` + `IncidentCategorySectionFields.tsx` |

## §7 Known dictionary issues — resolution status

| Issue | Dictionary note | Current code resolution |
|-------|-----------------|----------------------|
| `Blocked` duplicate (Road vs Bridge) | Excel duplicate column names | **Resolved in code:** distinct DB columns `road_blocked` and `bridge_blocked`; serializer and frontend use both. No rename needed. |
| `Dam_Level` duplicate (Hospital vs Health Center) | Excel duplicate column names | **Resolved in code:** distinct columns `hos_damage_level`, `hc_damage_level`, `school_damage_level`. API exposes school as `sch_damage_level` with serializer DB alias (fixed in this task). |
| `Muni_employees` vs `Muni_empl` | Naming drift | **Not renamed.** DB/serializer/frontend consistently use `muni_empl`. Excel answer key uses `MUNI_Empl`. **Flagged for your decision** if Excel export must read `Muni_employees`. |

## Gap categories (pre-fix)

### A — Fully wired (no action)

Sections where flag + DID + name + male/female casualties + automated rollups flow end-to-end when Tier-2 data exists:

- Lebanese Army, UNIFIL, Municipality (casualty subset), Hospital (casualty + name subset), Health Center (casualty subset), Press, Government building, Vehicles (including construction subtypes after `e2f0148`), School/University (classification + name), Religious & cultural (keyword classification + names)

### B — Mapper gaps fixed in this task

| Section | Fields | Fix |
|---------|--------|-----|
| Road / Bridge | `road`, `road_d_id`, `road_name`, `road_blocked`, `bridge`, `bridge_name`, `bridge_blocked` | New `_map_road_bridge()` — keyword classification from LLM `name` + `did` |
| Crossings & other | `litani`, `zahrani`, `drone_f`, `water`, `water_did`, `water_type`, `electric`, `electric_did`, `electric_type`, `olives_trees_d`, `mjnoub`, `mj_did`, `other_d`, `other_i`, `other_did` | Expanded `_map_crossings_other()` |
| Warning & classification | `genocide`, `building`, `apart` | Expanded `_map_warning_classification()` |
| Vehicles | `carc_d`, `carc_i` | Map `children_deaths/injuries` in `_map_car_casualties()` |
| School / University fallback | `other_did` | Set when falling back to `other` from school/religious unclassified names |
| Serializer | `sch_damage_level` | Added `_API_TO_DB_COLUMN` alias → `school_damage_level` |

### C — LLM schema not extended (flagged, not silently renamed)

These fields exist in DB, serializer, and frontend but Tier-2 LLM schema only asks for `did`, `name`, `casualties` (and `vehicles` for that category). **No extraction/prompt changes** were made per pipeline constraint.

| Section | Fields still LLM-unasked |
|---------|--------------------------|
| Lebanese Army / UNIFIL | `la_bldg`, `la_v`, `un_bldg`, `un_v` |
| Municipality | `muni_bldg`, `muni_empl` |
| School / University | `sch_damage_level` |
| Hospital | `hos_status`, `hos_damage_level`, `nbr_evap` |
| Health Center | `hc_rela`, `hc_damage_level` |
| Emergency / Civil Defense | `e_cars`, `car_nbr`, `emer_rela` |
| Government building | `gov_bui` |
| Road / Bridge | `road_blocked`, `bridge_blocked` (heuristic from `name` only; no dedicated LLM field) |
| Casualty demographics | `obs_duties`, `isf_gs`, `fire`, `arrested`, `lib_y_n` |

**Recommendation:** Extend `CATEGORY_DETAIL_RESPONSE_SCHEMA` per section in a follow-up extraction task, or accept that these remain manual/Excel-only until Phase 5+ enrichment.

### D — Automated rollups intentionally omitted from section API payloads

DB stores `hosd`/`hosi`, `hcd`/`hci`, `pressd`/`pressi`, `gbd`/`gbi` but serializer exposes component counts only; frontend mirrors that. Global `total_deaths`/`total_injuries` live on the incident header.

### E — Code drift (not in Excel dictionary)

| Field | Notes |
|-------|-------|
| `school_damage_level` | DB column name; API alias `sch_damage_level` |
| `incident_id` | PK/FK, not a data field |

## Full field-by-field table

Run for the complete pipe-delimited table:

```bash
python scripts/field_audit.py > Docs/FIELD_AUDIT_186_raw.txt
```

Columns: `field | section | type | db | llm | mapper | serializer | frontend | gap`

## Verification (Hospital + Municipality)

After mapper/serializer fixes, verify with:

```bash
# Find incidents with hospital or municipality gates set
docker compose exec db psql -U postgres -d war_news -c "
  SELECT i.id, d.hosp, d.hos_n, d.hosm_d, d.muni, d.muni_did, d.munim_d
  FROM incidents i
  JOIN incident_details d ON d.incident_id = i.id
  WHERE d.hosp IS TRUE OR d.muni IS TRUE
  LIMIT 5;
"
```

Then open `/admin/incidents/{id}` and confirm Hospital / Municipality sections render gated fields.

## Test results

See commit messages for pytest / vitest output after fixes.

## Manual browser checks

1. **Incidents list:** Header shows `Updated X hours ago` matching the newest incident timestamp, not poll time.
2. **Incidents list:** First summary card shows total incident count from API `total`.
3. **Incident detail:** Hospital row with `hosp=1` shows name and casualty counts; Municipality row shows `muni_did` + casualties when gate active.
4. **Road/Bridge:** Incident with road extraction shows road name and blocked flag when bulletin text includes blocking language.
