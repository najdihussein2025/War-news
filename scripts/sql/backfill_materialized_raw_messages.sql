-- Manual backfill: mark raw_messages as materialized when they already have
-- at least one related incident row.
--
-- Preconditions:
--   1. Apply the Alembic migration that adds message_status='materialized'.
--   2. Review this file before execution.
--
-- Scope:
--   Updates any raw_messages row currently stuck in status='parsed' that has
--   one or more incidents referencing it via incidents.raw_message_id.

BEGIN;

UPDATE raw_messages rm
SET
    status = 'materialized',
    error_message = NULL
WHERE rm.status = 'parsed'
  AND EXISTS (
      SELECT 1
      FROM incidents i
      WHERE i.raw_message_id = rm.id
  );

COMMIT;
