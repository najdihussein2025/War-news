-- Move raw messages held by fast-path's ambiguous multi-village sub-event gate
-- from status=parsed to the terminal held_for_review status.
-- Run manually AFTER migration 20260924_0064 (adds the enum value).
-- Review the SELECT output before running the UPDATE.

-- 1) Preview
SELECT id, status, error_message, fast_path_completed_at
FROM raw_messages
WHERE status = 'parsed'
  AND error_message LIKE 'Multiple sub-events lack explicit location binding%'
  AND NOT EXISTS (
    SELECT 1 FROM incidents
    WHERE incidents.raw_message_id = raw_messages.id
      AND incidents.is_deleted = false
  );

-- 2) Apply
BEGIN;
UPDATE raw_messages
SET status = 'held_for_review'
WHERE status = 'parsed'
  AND error_message LIKE 'Multiple sub-events lack explicit location binding%'
  AND NOT EXISTS (
    SELECT 1 FROM incidents
    WHERE incidents.raw_message_id = raw_messages.id
      AND incidents.is_deleted = false
  );
-- Check the row count matches the preview, then:
COMMIT;
