-- Step 1a: prompt's exact query (event_date only — same calendar day)
SELECT COUNT(*) AS prompt_sql_pair_count
FROM incidents a
JOIN incidents b ON a.id < b.id
  AND a.condition_id = b.condition_id
  AND a.village_id != b.village_id
  AND a.is_deleted = false AND b.is_deleted = false
  AND ABS(EXTRACT(EPOCH FROM (a.event_date - b.event_date))) <= 1800
WHERE word_similarity(a.khabar, b.khabar) >= 0.87
  AND a.khabar IS NOT NULL AND b.khabar IS NOT NULL;

-- Step 1b: live-equivalent 30-minute window on event_date+event_time
WITH timed AS (
  SELECT i.id, i.village_id, i.condition_id, i.khabar, i.event_date, i.event_time,
         (i.event_date + COALESCE(i.event_time, TIME '00:00')) AS event_dt
  FROM incidents i
  WHERE i.is_deleted = false
    AND i.khabar IS NOT NULL
    AND i.village_id IS NOT NULL
    AND i.condition_id IS NOT NULL
)
SELECT COUNT(*) AS live_30min_pair_count
FROM timed a
JOIN timed b ON a.id < b.id
  AND a.condition_id = b.condition_id
  AND a.village_id != b.village_id
  AND ABS(EXTRACT(EPOCH FROM (a.event_dt - b.event_dt))) <= 1800
WHERE word_similarity(a.khabar, b.khabar) >= 0.87;

-- Pair list with villages for the live 30min window
WITH timed AS (
  SELECT i.id, i.village_id, i.condition_id, i.khabar, i.event_date, i.event_time,
         i.raw_message_id, i.source_id,
         (i.event_date + COALESCE(i.event_time, TIME '00:00')) AS event_dt,
         COALESCE(v.ref_name_en, v.cad_name, v.acs_name) AS village_name,
         c.action_en AS condition_name
  FROM incidents i
  LEFT JOIN villages v ON v.id = i.village_id
  LEFT JOIN conditions c ON c.id = i.condition_id
  WHERE i.is_deleted = false
    AND i.khabar IS NOT NULL
    AND i.village_id IS NOT NULL
    AND i.condition_id IS NOT NULL
)
SELECT a.id::text AS id_a, b.id::text AS id_b,
       a.village_id AS vid_a, b.village_id AS vid_b,
       a.village_name AS village_a, b.village_name AS village_b,
       a.condition_name,
       a.event_dt AS t_a, b.event_dt AS t_b,
       ROUND(ABS(EXTRACT(EPOCH FROM (a.event_dt - b.event_dt)))::numeric, 0) AS gap_sec,
       ROUND(word_similarity(a.khabar, b.khabar)::numeric, 4) AS sim,
       LEFT(regexp_replace(a.khabar, E'[\n\r]+', ' ', 'g'), 100) AS khabar_a,
       LEFT(regexp_replace(b.khabar, E'[\n\r]+', ' ', 'g'), 100) AS khabar_b
FROM timed a
JOIN timed b ON a.id < b.id
  AND a.condition_id = b.condition_id
  AND a.village_id != b.village_id
  AND ABS(EXTRACT(EPOCH FROM (a.event_dt - b.event_dt))) <= 1800
WHERE word_similarity(a.khabar, b.khabar) >= 0.87
ORDER BY sim DESC, gap_sec ASC;
