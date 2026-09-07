-- Step 5 refined: distinguish same-message multi-village fan-out vs cross-message splits
WITH base AS (
  SELECT i.id, i.raw_message_id, i.village_id, i.condition_id, i.khabar,
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
  SELECT
    a.id AS id_a, b.id AS id_b,
    a.raw_message_id AS rm_a, b.raw_message_id AS rm_b,
    a.village_id AS vid_a, b.village_id AS vid_b,
    word_similarity(a.khabar, b.khabar) AS sim,
    ABS(EXTRACT(EPOCH FROM (a.t - b.t))) AS gap_sec,
    (a.raw_message_id IS NOT DISTINCT FROM b.raw_message_id) AS same_raw_message
  FROM base a
  JOIN base b ON a.id < b.id
    AND a.condition_id = b.condition_id
    AND a.village_id <> b.village_id
    AND ABS(EXTRACT(EPOCH FROM (a.t - b.t))) < 3600
  WHERE word_similarity(a.khabar, b.khabar) > 0.4
)
SELECT
  COUNT(*) FILTER (WHERE same_raw_message) AS same_message_pairs_gt_0_4,
  COUNT(*) FILTER (WHERE NOT same_raw_message) AS cross_message_pairs_gt_0_4,
  COUNT(*) FILTER (WHERE NOT same_raw_message AND sim > 0.5) AS cross_gt_0_5,
  COUNT(*) FILTER (WHERE NOT same_raw_message AND sim > 0.6) AS cross_gt_0_6,
  COUNT(*) FILTER (WHERE NOT same_raw_message AND sim > 0.7) AS cross_gt_0_7,
  COUNT(*) FILTER (WHERE NOT same_raw_message AND sim > 0.8) AS cross_gt_0_8,
  COUNT(*) FILTER (WHERE NOT same_raw_message AND sim > 0.9) AS cross_gt_0_9
FROM pairs;
