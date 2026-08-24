-- Scoped pipeline data reset. Review before running. Do not execute from the agent.
--
-- CLEARED (TRUNCATE, FK-safe order, RESTART IDENTITY for serial tables):
--   incident_updates, duplicate_matches, pipeline_sweep_jobs,
--   incident_details, incidents, raw_messages, ingestion_logs,
--   sweep_cursors
--
-- NOT TOUCHED:
--   villages, conditions, users, roles, sources,
--   audit_logs, login_logs, air_violations
--
-- Intentionally omitted because they do not exist in this database:
--   incident_media, field_definitions
--   (do not create them)
--
-- sources.last_cursor is untouched and remains stale (e.g. 731292 on CNRS
-- Webhook). After this reset, CNRS fetch MUST pass --after-id explicitly
-- with --hours 6; do not rely on last_cursor.
--
-- air_violations rows are kept. Their raw_message_id values are set to NULL
-- and the FK is dropped for the duration of TRUNCATE: PostgreSQL refuses to
-- TRUNCATE raw_messages while that FK exists, even with ON DELETE SET NULL.

BEGIN;

UPDATE air_violations SET raw_message_id = NULL;

ALTER TABLE air_violations
    DROP CONSTRAINT air_violations_raw_message_id_fkey;

TRUNCATE TABLE
    incident_updates,
    duplicate_matches,
    pipeline_sweep_jobs,
    incident_details,
    incidents,
    raw_messages,
    ingestion_logs,
    sweep_cursors
    RESTART IDENTITY;

ALTER TABLE air_violations
    ADD CONSTRAINT air_violations_raw_message_id_fkey
    FOREIGN KEY (raw_message_id) REFERENCES raw_messages (id) ON DELETE SET NULL;

COMMIT;
