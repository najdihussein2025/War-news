# db.md - Database Schema Reference

PostgreSQL schema as currently implemented by the project models and Alembic
migrations. This document should describe the tables that exist in this
codebase, not planned future tables.

Current schema: 12 tables.

## Conventions

- UUID primary keys on `users`, `auth_sessions`, and `incidents`.
- BIGSERIAL/SERIAL integer primary keys elsewhere.
- `TIMESTAMPTZ` is used for datetime columns.
- `incidents` uses soft delete through `is_deleted`.
- Duplicate prevention uses a partial unique index on `incidents.exact_hash`
  where `is_deleted = false`.

## Extensions

```sql
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "citext";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "vector";
```

## Custom Types

```sql
CREATE TYPE role_name AS ENUM ('super_admin', 'admin');
CREATE TYPE source_type AS ENUM ('telegram', 'twitter', 'facebook', 'website', 'api', 'manual', 'other');
CREATE TYPE message_status AS ENUM ('pending', 'parsed', 'duplicate', 'rejected', 'error');
CREATE TYPE did_value AS ENUM ('D', 'ID');
CREATE TYPE match_type AS ENUM ('exact', 'soft');
CREATE TYPE match_status AS ENUM ('pending', 'confirmed_duplicate', 'false_positive');
CREATE TYPE update_action AS ENUM ('create', 'edit', 'status_change', 'delete', 'undo');
```

## 1. Identity & Access

### `roles`

`id` (PK) · `name` (role_name, unique) · `created_at`

Seeded roles:

- `super_admin`
- `admin`

### `users`

`id` (UUID PK) · `username` (citext, unique) · `password_hash` · `full_name` ·
`role_id` (FK roles, ON DELETE RESTRICT) · `is_active` · `created_by`
(self-FK users, nullable, ON DELETE SET NULL) · `last_login_at` · `created_at` ·
`updated_at`

### `auth_sessions`

`id` (UUID PK) · `user_id` (FK users, ON DELETE CASCADE) · `token_hash`
(unique) · `expires_at` · `revoked_at` · `created_at`

## 2. Reference Data

### `villages`

Source: `Data/Villages.json`, imported from the ACS village data.

`id` (PK) · `acs_code` (unique) · `acs_name` · `cad_name` · `ref_name_en` ·
`ref_name_ar` · `caza_en` · `caza_ar` · `mohafaza_en` · `mohafaza_ar` ·
`coord_x` · `coord_y` · `is_active` · `created_at`

Indexes:

- `ix_villages_acs_name_trgm` on `acs_name`
- `ix_villages_ref_name_ar_trgm` on `ref_name_ar`

### `conditions`

Source: `Data/Conditions.json`, imported from the war actions data.

`id` (PK) · `action_en` · `action_ar` (unique) · `note` · `is_active` ·
`created_at`

Indexes:

- `ix_conditions_action_ar_trgm` on `action_ar`

## 3. Ingestion Pipeline

### `sources`

`id` (PK) · `type` (source_type) · `name` · `external_id` · `config` (jsonb) ·
`last_cursor` · `auth_secret_ref` · `is_active` · `created_at`

### `raw_messages`

`id` (PK) · `source_id` (FK sources, ON DELETE CASCADE) ·
`external_message_id` · `source_platform` · `source_name` · `raw_text` ·
`raw_payload` (jsonb) · `filter_result` (jsonb) ·
`low_confidence_relevance` · `extraction_result` (jsonb) · `message_datetime` ·
`received_at` · `status` (message_status) · `error_message`

Constraints and indexes:

- `UNIQUE (source_id, external_message_id)`
- Index on `source_platform`
- Index on `source_name`

### `ingestion_logs`

`id` (PK) · `source_id` (FK sources, ON DELETE CASCADE) · `messages_fetched` ·
`messages_parsed` · `messages_flagged` · `messages_failed` · `started_at` ·
`finished_at` · `created_at`

## 4. Core Incident Data

### `incidents`

`id` (UUID PK) · `raw_message_id` (FK raw_messages, nullable, ON DELETE SET NULL) ·
`village_id` (FK villages, ON DELETE RESTRICT) · `condition_id` (FK conditions,
ON DELETE RESTRICT) · `source_id` (FK sources, nullable, ON DELETE SET NULL) ·
`event_month` · `event_date` · `event_time` · `khabar` · `khabar_embedding`
(vector(384)) · `note` · `moh` · `martyrs` · `worker_name` · `source_link` ·
`source_link_2` · `total_deaths` · `total_injuries` · `deaths` · `injuries` ·
`injuries_extra` · `note_extra` · `exact_hash` · `incident_key` ·
`duplicate_flag` · `is_deleted` · `created_by` (FK users, nullable,
ON DELETE SET NULL) · `created_at` · `updated_at`

Indexes:

- `uq_incidents_exact_hash_active`: unique partial index on `exact_hash` where
  `is_deleted = false`
- `ix_incidents_khabar_embedding_hnsw`: HNSW vector index on `khabar_embedding`

### `incident_details`

1:1 with `incidents`; `incident_id` is both PK and FK with ON DELETE CASCADE.

Fields:

`incident_id` · `male_d` · `male_i` · `female_d` · `female_i` · `children_d` ·
`children_i` · `obs_duties` · `isf_gs` · `fire` · `arrested` · `lib_y_n` ·
`la` · `la_did` · `la_bldg` · `la_v` · `lam_d` · `lam_i` · `laf_d` · `laf_i` ·
`la_td` · `la_ti` · `unifil` · `un_did` · `un_bldg` · `un_v` · `unm_d` ·
`unm_i` · `unf_d` · `unf_i` · `un_td` · `un_ti` · `muni` · `muni_did` ·
`muni_bldg` · `muni_empl` · `munim_d` · `munim_i` · `munif_d` · `munif_i` ·
`muni_td` · `muni_ti` · `school` · `sch_did` · `school_name` ·
`school_damage_level` · `uni` · `uni_did` · `uni_name` · `church` ·
`chu_did` · `chu_n` · `mosque` · `mos_did` · `mosque_n` · `ceme` ·
`ceme_did` · `ceme_n` · `releg` · `releg_did` · `releg_n` · `archeo` ·
`arch_did` · `arch_n` · `hosp` · `hos_did` · `hos_status` · `hos_n` ·
`hos_damage_level` · `nbr_evap` · `hosm_d` · `hosm_i` · `hosf_d` · `hosf_i` ·
`hosd` · `hosi` · `hc` · `hc_rela` · `hc_did` · `hc_damage_level` · `hcm_d` ·
`hcm_i` · `hcf_d` · `hcf_i` · `hcd` · `hci` · `emer` · `e_cars` · `car_nbr` ·
`emer_rela` · `emer_d` · `emer_i` · `press` · `channel` · `press_did` ·
`pressm_d` · `pressm_i` · `pressf_d` · `pressf_i` · `pressd` · `pressi` ·
`gov` · `gov_bui` · `gov_n` · `gb_did` · `gbm_d` · `gbm_i` · `gbf_d` ·
`gbf_i` · `gbd` · `gbi` · `road` · `road_d_id` · `road_blocked` ·
`road_name` · `bridge` · `bridge_blocked` · `bridge_name` · `car` · `card` ·
`cari` · `carm_d` · `carm_i` · `carf_d` · `carf_i` · `carc_d` · `carc_i` ·
`moto` · `moto_did` · `moto_d` · `moto_i` · `con_veh` · `con_d` · `con_i` ·
`excavator` · `bulldozer` · `camion` · `bobcat` · `tracteur` · `total_con` ·
`crossing` · `litani` · `zahrani` · `drone_f` · `water` · `water_did` ·
`water_type` · `electric` · `electric_did` · `electric_type` ·
`olives_trees_d` · `mjnoub` · `mj_did` · `other` · `other_did` ·
`other_type` · `other_d` · `other_i` · `no_warning` · `warning` · `genocide` ·
`building` · `apart`

DID convention used by the project: every `*_did` field stores either `D`,
`ID`, or null and is paired with a controlling flag field in application logic.

## 5. Duplicates & Incident Updates

### `duplicate_matches`

`id` (PK) · `incident_id` (FK incidents, ON DELETE CASCADE) ·
`matched_incident_id` (FK incidents, ON DELETE CASCADE) · `match_type` ·
`similarity_score` · `status` · `resolved_by` (FK users, nullable,
ON DELETE SET NULL) · `created_at`

### `incident_updates`

`id` (PK) · `incident_id` (FK incidents, ON DELETE CASCADE) · `action` ·
`old_values` (jsonb) · `new_values` (jsonb) · `performed_by` (FK users,
nullable, ON DELETE SET NULL) · `created_at`

## Tables Not Present

These tables were removed from this reference because there are no current
SQLAlchemy models or Alembic migrations for them in the project:

- `incident_media`
- `audit_logs`
- `login_logs`
- `export_logs`
- `field_definitions`
