-- =====================================================================
-- Live DB damage audit (READ-ONLY SELECTs only).
--
-- Context: on 2026-10-19 the test suite was run by mistake against the
-- deployment database `war_news_dev` (Compose project `war-news`).
--
-- WINDOW IS APPROXIMATE: the backend container was recreated at
-- 07:23:48 UTC and the full test run finished before about 07:36 UTC.
-- The window below (07:20-07:45 UTC) is deliberately wider than that.
--
-- Run it yourself in your SQL client (pgAdmin/DBeaver) connected to the
-- live database. Nothing in this file writes; it was never executed by
-- Claude.
-- =====================================================================

-- Window parameters used below (kept inline so each query is standalone):
--   start = '2026-10-19 07:20:00+00'
--   end   = '2026-10-19 07:45:00+00'

-- ---------------------------------------------------------------------
-- Q1. Raw messages stuck in non-terminal pipeline states for > 30 min,
--     by state and source.  (Terminal: materialized, duplicate, rejected,
--     error, routed_air_violation, held_for_review, summary_handled.)
-- ---------------------------------------------------------------------
SELECT rm.status,
       COALESCE(rm.source_name, s.name) AS source,
       rm.processing_claim_stage,
       COUNT(*)                          AS n,
       MIN(rm.received_at)               AS oldest_received_at,
       MAX(rm.received_at)               AS newest_received_at
FROM raw_messages rm
LEFT JOIN sources s ON s.id = rm.source_id
WHERE rm.status IN ('pending', 'parsed')
  AND rm.received_at < now() - interval '30 minutes'
GROUP BY rm.status, COALESCE(rm.source_name, s.name), rm.processing_claim_stage
ORDER BY n DESC;

-- ---------------------------------------------------------------------
-- Q2. Current rows in pipeline_sweep_jobs with status and timestamps.
--     (tests/test_pipeline_jobs.py ran `DELETE FROM pipeline_sweep_jobs`.)
-- ---------------------------------------------------------------------
SELECT id, status, max_rows, use_advisory_lock,
       requested_at, claimed_at, finished_at
FROM pipeline_sweep_jobs
ORDER BY id DESC
LIMIT 200;

SELECT status, COUNT(*) AS n, MIN(requested_at) AS first_requested, MAX(requested_at) AS last_requested
FROM pipeline_sweep_jobs
GROUP BY status;

-- ---------------------------------------------------------------------
-- Q3. pipeline_stage_runs inside the window, grouped by stage.
-- ---------------------------------------------------------------------
SELECT stage_name, sweep_type,
       COUNT(*)            AS runs,
       SUM(rows_claimed)   AS rows_claimed,
       SUM(rows_succeeded) AS rows_succeeded,
       SUM(rows_failed)    AS rows_failed,
       BOOL_OR(aborted)    AS any_aborted,
       MIN(started_at)     AS first_started,
       MAX(finished_at)    AS last_finished
FROM pipeline_stage_runs
WHERE started_at >= '2026-10-19 07:20:00+00'
  AND started_at <  '2026-10-19 07:45:00+00'
GROUP BY stage_name, sweep_type
ORDER BY stage_name, sweep_type;

-- ---------------------------------------------------------------------
-- Q4. Test-fixture residue.  Values were collected from the test files:
--   * tests build unique rows with a 32-hex uuid4().hex marker, e.g.
--       Source.name "clustering-atomicity-<hex>", "Edit source <hex>",
--       "Incident source <hex>", "CNRS test <hex>", "Concurrency Test"
--       Source.external_id "air-violation-concurrency-<hex>",
--       "air-window-source-<hex>", "source-test-<hex>",
--       "red-alert-source-test-<hex>", "red-alert-test-<hex>"
--       Village.ref_name_en "Arnoun Test <hex>", "Air Village <hex>",
--       "Village <hex>", "Alternate village <hex>", "Anchor village <hex>"
--       (caza_en "Test Caza" / "Nabatiye" with those names)
--       RawMessage.external_message_id "<hex>-representative",
--       "<hex>-member", "message-<hex>", "telegram:<hex>",
--       "telegram:redlinkleb:<hex>", "<hex>-generic-N", "<hex>-<source>"
--       RawMessage.raw_text "تحليق طيران حربي فوق #الجنوب", "drone over ..."
--   * "Red Alert Lebanon" / "CNRS Webhook" are REAL source names too, so
--     they are only matched together with a hex marker in external_id.
-- Most of these tests roll back through a savepoint/outer transaction,
-- so zero rows is the expected result; committed rows are the damage.
-- ---------------------------------------------------------------------

-- Q4a. sources
SELECT id, type, name, external_id
FROM sources
WHERE name ~ '^(clustering-atomicity|Edit source|Incident source|CNRS test) [0-9a-f]{32}$'
   OR name = 'Concurrency Test'
   OR external_id ~ '^(air-violation-concurrency|air-window-source|source-test|red-alert-source-test|red-alert-test)-[0-9a-f]{32}$'
ORDER BY id;

-- Q4b. villages
SELECT id, acs_code, ref_name_en, ref_name_ar, caza_en
FROM villages
WHERE ref_name_en ~ '^(Arnoun Test|Air Village|Village|Alternate village|Anchor village) [0-9a-f]{32}$'
   OR caza_en = 'Test Caza'
ORDER BY id;

-- Q4c. raw_messages
SELECT rm.id, rm.source_id, rm.external_message_id, rm.status, rm.received_at
FROM raw_messages rm
WHERE rm.external_message_id ~ '[0-9a-f]{32}'
  AND (rm.external_message_id ~ '^[0-9a-f]{32}-(representative|member|generic-[0-9]+)$'
       OR rm.external_message_id ~ '^message-[0-9a-f]{32}$'
       OR rm.external_message_id ~ '^telegram:([a-z]+:)?[0-9a-f]{32}$')
   OR rm.source_id IN (
        SELECT id FROM sources
        WHERE name ~ '^(clustering-atomicity|Edit source|Incident source|CNRS test) [0-9a-f]{32}$'
           OR external_id ~ '^(air-window-source|source-test|red-alert-source-test|red-alert-test)-[0-9a-f]{32}$')
ORDER BY rm.id;

-- Q4d. incidents tied to fixture sources / villages / raw messages
SELECT i.id, i.village_id, i.source_id, i.raw_message_id, i.created_at
FROM incidents i
WHERE i.source_id IN (
        SELECT id FROM sources
        WHERE name ~ '^(Edit source|Incident source|CNRS test) [0-9a-f]{32}$')
   OR i.village_id IN (
        SELECT id FROM villages
        WHERE ref_name_en ~ '^(Village|Alternate village|Anchor village|Air Village|Arnoun Test) [0-9a-f]{32}$')
   OR i.raw_message_id IN (
        SELECT id FROM raw_messages
        WHERE external_message_id ~ '^(message-|telegram:)[0-9a-f]{32}$')
ORDER BY i.created_at;

-- Q4e. incident_details for those incidents
SELECT d.incident_id
FROM incident_details d
WHERE d.incident_id IN (
    SELECT i.id FROM incidents i
    WHERE i.source_id IN (SELECT id FROM sources WHERE name ~ '^(Edit source|Incident source|CNRS test) [0-9a-f]{32}$')
       OR i.village_id IN (SELECT id FROM villages WHERE ref_name_en ~ '^(Village|Alternate village|Anchor village) [0-9a-f]{32}$'));

-- Q4f. incident_updates in the window, and any for fixture incidents
SELECT u.id, u.incident_id, u.created_at
FROM incident_updates u
WHERE u.created_at >= '2026-10-19 07:20:00+00'
  AND u.created_at <  '2026-10-19 07:45:00+00'
ORDER BY u.id;
