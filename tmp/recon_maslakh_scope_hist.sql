-- Threshold histogram for cross-village pairs (14d, 1h window, same condition)
WITH base AS (
  SELECT i.id, i.village_id, i.condition_id, i.khabar,
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
  SELECT word_similarity(a.khabar, b.khabar) AS sim
  FROM base a
  JOIN base b ON a.id < b.id
    AND a.condition_id = b.condition_id
    AND a.village_id <> b.village_id
    AND ABS(EXTRACT(EPOCH FROM (a.t - b.t))) < 3600
  WHERE word_similarity(a.khabar, b.khabar) > 0.4
)
SELECT
  COUNT(*) FILTER (WHERE sim > 0.4) AS gt_0_4,
  COUNT(*) FILTER (WHERE sim > 0.5) AS gt_0_5,
  COUNT(*) FILTER (WHERE sim > 0.6) AS gt_0_6,
  COUNT(*) FILTER (WHERE sim > 0.7) AS gt_0_7,
  COUNT(*) FILTER (WHERE sim > 0.8) AS gt_0_8,
  COUNT(*) FILTER (WHERE sim > 0.9) AS gt_0_9,
  round(AVG(sim)::numeric, 4) AS avg_sim,
  round(MAX(sim)::numeric, 4) AS max_sim
FROM pairs;
