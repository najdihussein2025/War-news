-- Step 1 diagnostics for cross-village cleanup (live data, no 14d cutoff)

-- A. Prompt SQL as written (event_date - event_date is integer days; this will error)
-- skipped

-- B. Timestamp-fixed unnormalized (user SQL + event_date+event_time)
SELECT 'unnormalized_30min' AS bucket, COUNT(*) AS n
FROM incidents a
JOIN incidents b ON a.id < b.id
  AND a.condition_id = b.condition_id
  AND a.village_id != b.village_id
  AND a.is_deleted = false AND b.is_deleted = false
  AND ABS(EXTRACT(EPOCH FROM (
        (a.event_date + COALESCE(a.event_time, TIME '00:00'))
      - (b.event_date + COALESCE(b.event_time, TIME '00:00'))
      ))) <= 1800
WHERE word_similarity(a.khabar, b.khabar) >= 0.87;

-- C. Production-normalized (same as find_cross_village_dedup_candidates)
-- Normalization inlined to match app.core.text_normalization.normalize_arabic_sql
WITH norm AS (
  SELECT id, village_id, condition_id, khabar, event_date, event_time, raw_message_id, is_deleted,
         btrim(regexp_replace(
           btrim(btrim(
             replace(translate(
               regexp_replace(khabar, '[\u064b-\u0652\u0640]', '', 'g'),
               'أإآٱة', 'ااااه'), 'ى', 'ي')),
             '،.؛!؟"'''),
           '\s+', ' ', 'g')) AS khabar_norm
  FROM incidents
  WHERE is_deleted = false AND khabar IS NOT NULL
    AND village_id IS NOT NULL AND condition_id IS NOT NULL
)
SELECT 'normalized_30min' AS bucket, COUNT(*) AS n
FROM norm a
JOIN norm b ON a.id < b.id
  AND a.condition_id = b.condition_id
  AND a.village_id != b.village_id
  AND ABS(EXTRACT(EPOCH FROM (
        (a.event_date + COALESCE(a.event_time, TIME '00:00'))
      - (b.event_date + COALESCE(b.event_time, TIME '00:00'))
      ))) <= 1800
WHERE word_similarity(a.khabar_norm, b.khabar_norm) >= 0.87;
