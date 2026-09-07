-- Step 5 top pairs detail
WITH base AS (
  SELECT i.id, i.village_id, i.condition_id, i.khabar, i.event_date,
         COALESCE(r.message_datetime, r.received_at, i.created_at) AS t
  FROM incidents i
  LEFT JOIN raw_messages r ON r.id = i.raw_message_id
  WHERE i.is_deleted = false
    AND i.khabar IS NOT NULL
    AND i.village_id IS NOT NULL
    AND i.condition_id IS NOT NULL
    AND COALESCE(r.message_datetime, r.received_at, i.created_at) >= NOW() - INTERVAL '14 days'
)
SELECT a.id AS id_a, b.id AS id_b,
       a.village_id AS vid_a, b.village_id AS vid_b,
       va.acs_name AS village_a, vb.acs_name AS village_b,
       a.condition_id AS cid,
       a.t AS t_a, b.t AS t_b,
       ROUND(ABS(EXTRACT(EPOCH FROM (a.t - b.t)))::numeric, 0) AS gap_sec,
       round(word_similarity(a.khabar, b.khabar)::numeric, 4) AS sim,
       LEFT(regexp_replace(a.khabar, E'[\n\r]+', ' ', 'g'), 90) AS khabar_a,
       LEFT(regexp_replace(b.khabar, E'[\n\r]+', ' ', 'g'), 90) AS khabar_b
FROM base a
JOIN base b ON a.id < b.id
  AND a.condition_id = b.condition_id
  AND a.village_id <> b.village_id
  AND ABS(EXTRACT(EPOCH FROM (a.t - b.t))) < 3600
JOIN villages va ON va.id = a.village_id
JOIN villages vb ON vb.id = b.village_id
WHERE word_similarity(a.khabar, b.khabar) > 0.4
ORDER BY sim DESC
LIMIT 50;
