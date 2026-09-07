-- Step 5: cross-village high text-similarity pairs within 1h (by message_datetime)
-- Last 14 days. Count + top 50.
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
),
pairs AS (
  SELECT a.id AS id_a, b.id AS id_b,
         a.village_id AS vid_a, b.village_id AS vid_b,
         a.condition_id AS cid,
         a.t AS t_a, b.t AS t_b,
         ABS(EXTRACT(EPOCH FROM (a.t - b.t))) AS gap_sec,
         word_similarity(a.khabar, b.khabar) AS sim,
         a.khabar AS khabar_a,
         b.khabar AS khabar_b
  FROM base a
  JOIN base b ON a.id < b.id
    AND a.condition_id = b.condition_id
    AND a.village_id <> b.village_id
    AND ABS(EXTRACT(EPOCH FROM (a.t - b.t))) < 3600
  WHERE word_similarity(a.khabar, b.khabar) > 0.4
)
SELECT COUNT(*) AS pair_count FROM pairs;
