-- Historical note-pollution cleanup — verification queries only.
-- The mutating work lives in:
--   scripts/review/cleanup_historical_merge_note_pollution.py
-- Run that script with no flags for dry-run; --apply only after review.
--
-- Pre-apply scope check (expect ~335 as of 2026-09-07 verification; may grow
-- only if merges happened before be91e0d was live):

SELECT COUNT(*) AS polluted_active_incidents
FROM incidents
WHERE is_deleted = false
  AND note LIKE '%Automated duplicate merge from raw_message_id=%';

-- Post-apply: should be 0
-- SELECT COUNT(*) AS remaining_polluted
-- FROM incidents
-- WHERE is_deleted = false
--   AND note LIKE '%Automated duplicate merge from raw_message_id=%';

-- Post-apply: pipeline_merge rows for formerly polluted incidents should have merged_from
-- SELECT
--   COUNT(*) AS pipeline_merge_rows,
--   COUNT(*) FILTER (WHERE new_values ? 'merged_from') AS with_merged_from
-- FROM incident_updates
-- WHERE action = 'pipeline_merge';
