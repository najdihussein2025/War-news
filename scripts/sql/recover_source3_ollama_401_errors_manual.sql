-- Manual review / execution only.
-- Scope confirmed on 2026-08-26:
--   source_id=3, status='error' rows: 1371
--   subset matching this WHERE clause: 1258

-- Preview the exact rows that would be reset.
SELECT COUNT(*) AS rows_to_reset
FROM raw_messages
WHERE source_id = 3
  AND status = 'error'
  AND extraction_result IS NULL
  AND error_message ILIKE '%401 Unauthorized%'
  AND error_message ILIKE '%/api/chat%';

-- Reset only the rows tied to the historical Ollama auth failure.
UPDATE raw_messages
SET status = 'parsed',
    error_message = NULL
WHERE source_id = 3
  AND status = 'error'
  AND extraction_result IS NULL
  AND error_message ILIKE '%401 Unauthorized%'
  AND error_message ILIKE '%/api/chat%';
