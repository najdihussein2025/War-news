BEGIN;

-- Preview before update
SELECT
  split_part(external_message_id, ':', 1) AS derived_platform,
  COUNT(*)
FROM raw_messages
WHERE source_platform IS NULL
GROUP BY derived_platform
ORDER BY 2 DESC;

-- Backfill source_platform from external_message_id prefix,
-- excluding obvious test/dev traffic (prefix starting with "cnrs-lan-test")
UPDATE raw_messages
SET source_platform = split_part(external_message_id, ':', 1)
WHERE source_platform IS NULL
  AND external_message_id NOT LIKE 'cnrs-lan-test%';

-- Backfill source_name from the owning source's name
-- (only real signal available - CNRS sends no per-message account/channel)
UPDATE raw_messages rm
SET source_name = s.name
FROM sources s
WHERE rm.source_id = s.id
  AND rm.source_name IS NULL;

-- Verify
SELECT source_platform, source_name, COUNT(*)
FROM raw_messages
GROUP BY source_platform, source_name
ORDER BY 3 DESC;

SELECT COUNT(*) AS still_null_platform
FROM raw_messages WHERE source_platform IS NULL;

SELECT COUNT(*) AS still_null_name
FROM raw_messages WHERE source_name IS NULL;

COMMIT;
