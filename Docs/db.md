# db.md - Database Schema Reference

PostgreSQL schema as currently represented by the SQLAlchemy models and
Alembic migrations in this codebase. This document describes implemented
tables, not planned future tables.

Current schema: 20 tables.

## Conventions

- UUID primary keys on `users`, `auth_sessions`, `login_logs`, `audit_logs`,
  and `incidents`.
- BIGSERIAL/BIGINT integer primary keys on most ingestion and news tables.
- `TIMESTAMPTZ` is used for datetime columns.
- `JSONB` stores source payloads and LLM/matching outputs.
- `vector(384)` stores raw-message and incident embeddings.
- Incidents use soft delete through `incidents.is_deleted`.
- Active incident exact hashes are protected by a partial unique index on
  `incidents.exact_hash` where `is_deleted = false`.

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
CREATE TYPE message_status AS ENUM ('pending', 'parsed', 'duplicate', 'rejected', 'error', 'routed_air_violation');
CREATE TYPE did_value AS ENUM ('D', 'ID');
CREATE TYPE match_type AS ENUM ('exact', 'soft');
CREATE TYPE match_status AS ENUM ('pending', 'confirmed_duplicate', 'false_positive');
CREATE TYPE update_action AS ENUM ('create', 'edit', 'pipeline_merge', 'status_change', 'delete', 'undo');
CREATE TYPE trust_tier AS ENUM ('official', 'trusted', 'detail');
```

## 1. Identity and Access

### `roles`

`id` (PK) · `name` (role_name, unique) · `created_at`

Seeded roles:

- `super_admin`
- `admin`

### `users`

`id` (UUID PK) · `username` (citext, unique) · `password_hash` · `full_name` ·
`role_id` (FK roles, ON DELETE RESTRICT) · `is_active` · `created_by`
(self-FK users, nullable, ON DELETE SET NULL) · `last_login_at` ·
`failed_login_attempts` · `locked_until` · `created_at` · `updated_at`

### `auth_sessions`

`id` (UUID PK) · `user_id` (FK users, ON DELETE CASCADE) · `token_hash`
(unique) · `expires_at` · `revoked_at` · `created_at`

### `login_throttles`

`client_ip` (PK) · `failed_attempts` · `locked_until`

Used for IP-level login throttling in addition to per-user lockout fields.

## 2. Logs

### `login_logs`

`id` (UUID PK) · `user_id` (FK users, nullable, ON DELETE SET NULL) ·
`username` · `success` · `client_ip` · `failure_reason` · `created_at`

Indexes:

- `ix_login_logs_created_at`
- `ix_login_logs_username`

### `audit_logs`

`id` (UUID PK) · `action` · `target_type` · `target_id` · `actor_id`
(FK users, nullable, ON DELETE SET NULL) · `actor_name` · `client_ip` (inet) ·
`old_values` (jsonb) · `new_values` (jsonb) · `created_at`

Indexes exist on `action`, `target_type`, `target_id`, and `created_at`.

### `ingestion_logs`

`id` (PK) · `source_id` (FK sources, ON DELETE CASCADE) · `messages_fetched` ·
`messages_parsed` · `messages_flagged` · `messages_failed` ·
`messages_blocked` · `source_platforms` (jsonb array) · `platform_breakdown`
(jsonb object) · `status` · `error_message` · `retry_of_id`
(self-FK ingestion_logs, nullable, ON DELETE SET NULL) · `started_at` ·
`finished_at` · `created_at`

## 3. Sources and Content Origins

### `sources`

`id` (PK) · `type` (source_type) · `name` · `external_id` · `config` (jsonb) ·
`last_cursor` · `auth_secret_ref` · `is_active` · `created_at`

### `source_platform`

`id` (PK) · `platform` · `name` · `created_at`

Constraints:

- `UNIQUE (platform, name)` via `uq_source_platform_platform_name`

Used as the normalized source-platform reference for raw messages.

### `content_source_blocks`

`id` (PK) · `source_platform` · `origin_account` · `is_blocked` ·
`blocked_at` · `blocked_by` (FK users, nullable, ON DELETE SET NULL) ·
`created_at`

Constraints:

- `UNIQUE (source_platform, origin_account)` via
  `uq_content_source_blocks_platform_account`

## 4. Reference Data

### `villages`

Source: `Data/Villages.json`, imported from ACS village data.

`id` (PK) · `acs_code` (unique) · `acs_name` · `cad_name` · `ref_name_en` ·
`ref_name_ar` · `caza_en` · `caza_ar` · `mohafaza_en` · `mohafaza_ar` ·
`coord_x` · `coord_y` · `is_active` · `created_at`

Indexes:

- `ix_villages_acs_name_trgm`
- `ix_villages_ref_name_ar_trgm`

### `conditions`

Source: `Data/Conditions.json`, imported from the war-action vocabulary.

`id` (PK) · `action_en` · `action_ar` (unique) · `note` · `is_active` ·
`created_at`

Indexes:

- `ix_conditions_action_ar_trgm`

### `channel_trust_tiers`

`id` (PK) · `channel_name` (unique) · `tier` (trust_tier) · `created_at`

Used by clustering to prefer representative messages from higher-trust content
origins.

## 5. Raw Message Pipeline

### `raw_messages`

`id` (PK) · `source_id` (FK sources, ON DELETE CASCADE) ·
`external_message_id` · `source_platform` · `source_name` ·
`source_platform_id` (FK source_platform, nullable, ON DELETE SET NULL) ·
`origin_platform` · `origin_account` · `raw_text` · `raw_payload` (jsonb) ·
`cnrs_classification` (jsonb) · `filter_result` (jsonb) ·
`low_confidence_relevance` · `extraction_result` (jsonb) ·
`match_result` (jsonb) · `content_embedding` (vector(384)) ·
`duplicate_of_id` (self-FK raw_messages, nullable, ON DELETE SET NULL) ·
`message_datetime` · `received_at` · `status` (message_status) ·
`error_message` · `extraction_retry_count`

Constraints and indexes:

- `UNIQUE (source_id, external_message_id)` via
  `uq_raw_messages_source_external_message`
- Index on `source_platform`
- Index on `source_name`
- Index on `duplicate_of_id`

Status values:

- `pending`: stored but not relevance-filtered yet.
- `parsed`: relevant enough to continue through extraction/matching.
- `duplicate`: duplicate raw message linked through `duplicate_of_id`.
- `rejected`: failed relevance filtering.
- `error`: terminal pipeline error or permanently unmaterializable result.
- `routed_air_violation`: matched to an air-violation condition and not
  materialized as a standard incident.

### `sweep_cursors`

`sweep_name` (PK) · `last_processed_id` · `updated_at`

Used by incremental sweep/worker scripts to avoid reprocessing rows already
seen by that sweep.

## 6. Core Incident Data

### `incidents`

`id` (UUID PK) · `raw_message_id` (FK raw_messages, nullable, ON DELETE SET
NULL) · `village_id` (FK villages, nullable, ON DELETE RESTRICT) ·
`condition_id` (FK conditions, nullable, ON DELETE RESTRICT) · `source_id`
(FK sources, nullable, ON DELETE SET NULL) · `event_month` · `event_date` ·
`event_time` · `khabar` · `khabar_embedding` (vector(384)) · `note` · `moh` ·
`martyrs` · `worker_name` · `source_link` · `source_link_2` · `total_deaths` ·
`total_injuries` · `deaths` · `injuries` · `injuries_extra` · `note_extra` ·
`note_extra_2` · `exact_hash` · `incident_key` · `duplicate_flag` ·
`details_pending` · `is_deleted` · `created_by` (FK users, nullable,
ON DELETE SET NULL) · `created_at` · `updated_at`

Indexes:

- `uq_incidents_exact_hash_active`: unique partial index on `exact_hash` where
  `is_deleted = false`
- `ix_incidents_khabar_embedding_hnsw`: HNSW vector index on `khabar_embedding`

Notes:

- `village_id` and `condition_id` are nullable to support imported or
  verification-needed records where the reference match is unresolved.
- Fast-path incidents start with `details_pending = true` until tier-2 detail
  fill completes.
- `source_link_2`, `injuries_extra`, `note_extra`, and `note_extra_2` preserve
  legacy workbook values whose semantics still need confirmation.

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

DID convention: every `*_did` field stores `D`, `ID`, or null and is paired
with a controlling boolean flag in application logic. The database enum limits
allowed non-null values, while clearing/required behavior is enforced by
services/UI.

## 7. Air Violations

### `air_violations`

`id` (PK) · `raw_message_id` (FK raw_messages, nullable, ON DELETE SET NULL) ·
`condition_id` (FK conditions, ON DELETE RESTRICT) · `source_id`
(FK sources, ON DELETE RESTRICT) · `caza_en` · `caza_ar` · `event_month` ·
`event_date` · `event_time` · `khabar` · `note_1` · `note_2` · `source_link` ·
`created_at`

Indexes:

- Index on `condition_id`
- Index on `event_date`

Expected condition IDs are the air-activity conditions used by the pipeline:
`35`, `36`, `38`, and `45`.

## 8. Duplicates and Incident Updates

### `duplicate_matches`

`id` (PK) · `incident_id` (FK incidents, ON DELETE CASCADE) ·
`matched_incident_id` (FK incidents, nullable, ON DELETE CASCADE) ·
`raw_message_id` (FK raw_messages, nullable, ON DELETE SET NULL) ·
`match_type` (match_type) · `similarity_score` · `status` (match_status) ·
`resolved_by` (FK users, nullable, ON DELETE SET NULL) · `created_at`

`matched_incident_id` is nullable so fast-path duplicate evidence can be
recorded against a raw message even when the duplicate candidate did not become
a new incident.

### `incident_updates`

`id` (PK) · `incident_id` (FK incidents, ON DELETE CASCADE) · `action`
(update_action) · `old_values` (jsonb) · `new_values` (jsonb) · `performed_by`
(FK users, nullable, ON DELETE SET NULL) · `created_at`

`pipeline_merge` records automated merges from the materialization/dedup flow.

## Tables Not Present

These tables are not represented by current SQLAlchemy models:

- `incident_media`
- `export_logs`
- `field_definitions`
