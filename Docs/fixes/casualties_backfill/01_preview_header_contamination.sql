-- Read-only preview: positive casualties lacking body evidence or introduced by a merge.
SELECT i.id, i.raw_message_id, i.total_deaths, i.total_injuries, i.verification_reason
FROM incidents i
LEFT JOIN raw_messages rm ON rm.id = i.raw_message_id
WHERE NOT i.is_deleted
  AND (COALESCE(i.total_deaths, 0) > 0 OR COALESCE(i.total_injuries, 0) > 0)
  AND (
    COALESCE(i.quality_flags::text, '') ILIKE '%header%'
    OR COALESCE(i.quality_flags::text, '') ILIKE '%memorial%'
    OR COALESCE(i.quality_flags::text, '') ILIKE '%merged_from_snapshot%'
  )
ORDER BY i.event_date, i.id;
