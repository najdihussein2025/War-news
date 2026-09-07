-- ========== STEP 3: Duplicate matches breakdown ==========
SELECT match_type, status, COUNT(*) AS n,
       ROUND(AVG(similarity_score)::numeric, 4) AS avg_sim,
       ROUND(MIN(similarity_score)::numeric, 4) AS min_sim,
       ROUND(MAX(similarity_score)::numeric, 4) AS max_sim
FROM duplicate_matches
WHERE status = 'pending'
GROUP BY match_type, status
ORDER BY match_type;

SELECT status, COUNT(*) AS n
FROM duplicate_matches
GROUP BY status ORDER BY 2 DESC;

-- Pending with matched_incident_id (review queue) vs fast-path only
SELECT
  COUNT(*) FILTER (WHERE matched_incident_id IS NOT NULL) AS pending_with_pair,
  COUNT(*) FILTER (WHERE matched_incident_id IS NULL) AS pending_fast_path_null_pair,
  COUNT(*) AS pending_total
FROM duplicate_matches WHERE status = 'pending';

-- Similarity score distribution for pending pairs
WITH pending AS (
  SELECT similarity_score
  FROM duplicate_matches
  WHERE status = 'pending' AND matched_incident_id IS NOT NULL
)
SELECT
  CASE
    WHEN similarity_score < 0.50 THEN 'lt_0.50'
    WHEN similarity_score < 0.65 THEN '0.50_0.65'
    WHEN similarity_score < 0.78 THEN '0.65_0.78'
    WHEN similarity_score < 0.80 THEN '0.78_0.80'
    WHEN similarity_score < 0.86 THEN '0.80_0.86'
    ELSE 'ge_0.86'
  END AS sim_bucket,
  COUNT(*) AS n,
  ROUND(AVG(similarity_score)::numeric, 4) AS avg_sim
FROM pending
GROUP BY 1
ORDER BY MIN(similarity_score);

-- Time gaps for pending pairs (using incident event times / raw message times)
WITH pending AS (
  SELECT
    dm.id AS match_id,
    dm.incident_id,
    dm.matched_incident_id,
    dm.similarity_score,
    dm.match_type,
    dm.created_at AS match_created_at,
    COALESCE(r1.message_datetime, r1.received_at, i1.created_at) AS t1,
    COALESCE(r2.message_datetime, r2.received_at, i2.created_at) AS t2
  FROM duplicate_matches dm
  JOIN incidents i1 ON i1.id = dm.incident_id
  JOIN incidents i2 ON i2.id = dm.matched_incident_id
  LEFT JOIN raw_messages r1 ON r1.id = i1.raw_message_id
  LEFT JOIN raw_messages r2 ON r2.id = i2.raw_message_id
  WHERE dm.status = 'pending'
)
SELECT
  CASE
    WHEN ABS(EXTRACT(EPOCH FROM (t1 - t2))) <= 120 THEN 'le_2min'
    WHEN ABS(EXTRACT(EPOCH FROM (t1 - t2))) <= 1800 THEN 'le_30min'
    WHEN ABS(EXTRACT(EPOCH FROM (t1 - t2))) <= 21600 THEN 'le_6h'
    ELSE 'gt_6h'
  END AS time_gap_bucket,
  COUNT(*) AS n,
  ROUND(AVG(similarity_score)::numeric, 4) AS avg_sim,
  ROUND(MIN(similarity_score)::numeric, 4) AS min_sim,
  ROUND(MAX(similarity_score)::numeric, 4) AS max_sim
FROM pending
GROUP BY 1
ORDER BY MIN(ABS(EXTRACT(EPOCH FROM (t1 - t2))));

-- Pending > 6h: historical vs new relative to Phase 1 landing (cbaf147 @ 2026-09-07 12:51:07 +0300)
WITH pending AS (
  SELECT
    dm.id AS match_id,
    dm.created_at AS match_created_at,
    dm.similarity_score,
    ABS(EXTRACT(EPOCH FROM (
      COALESCE(r1.message_datetime, r1.received_at, i1.created_at)
      - COALESCE(r2.message_datetime, r2.received_at, i2.created_at)
    ))) AS gap_seconds
  FROM duplicate_matches dm
  JOIN incidents i1 ON i1.id = dm.incident_id
  JOIN incidents i2 ON i2.id = dm.matched_incident_id
  LEFT JOIN raw_messages r1 ON r1.id = i1.raw_message_id
  LEFT JOIN raw_messages r2 ON r2.id = i2.raw_message_id
  WHERE dm.status = 'pending'
)
SELECT
  COUNT(*) FILTER (WHERE gap_seconds > 21600) AS pending_gt_6h,
  COUNT(*) FILTER (WHERE gap_seconds > 21600 AND match_created_at < TIMESTAMPTZ '2026-09-07 12:51:07+03') AS gt6h_before_phase1,
  COUNT(*) FILTER (WHERE gap_seconds > 21600 AND match_created_at >= TIMESTAMPTZ '2026-09-07 12:51:07+03') AS gt6h_after_phase1,
  COUNT(*) FILTER (WHERE match_created_at >= TIMESTAMPTZ '2026-09-07 12:51:07+03') AS pending_created_after_phase1,
  COUNT(*) FILTER (WHERE match_created_at < TIMESTAMPTZ '2026-09-07 12:51:07+03') AS pending_created_before_phase1
FROM pending;

-- New pending matches after Phase 1: time gap + sim distribution
WITH pending AS (
  SELECT
    dm.id AS match_id,
    dm.similarity_score,
    dm.match_type,
    dm.created_at,
    ABS(EXTRACT(EPOCH FROM (
      COALESCE(r1.message_datetime, r1.received_at, i1.created_at)
      - COALESCE(r2.message_datetime, r2.received_at, i2.created_at)
    ))) AS gap_seconds
  FROM duplicate_matches dm
  JOIN incidents i1 ON i1.id = dm.incident_id
  JOIN incidents i2 ON i2.id = dm.matched_incident_id
  LEFT JOIN raw_messages r1 ON r1.id = i1.raw_message_id
  LEFT JOIN raw_messages r2 ON r2.id = i2.raw_message_id
  WHERE dm.status = 'pending'
    AND dm.created_at >= TIMESTAMPTZ '2026-09-07 12:51:07+03'
)
SELECT
  CASE
    WHEN gap_seconds <= 120 THEN 'le_2min'
    WHEN gap_seconds <= 1800 THEN 'le_30min'
    WHEN gap_seconds <= 21600 THEN 'le_6h'
    ELSE 'gt_6h'
  END AS time_gap_bucket,
  COUNT(*) AS n,
  ROUND(AVG(similarity_score)::numeric, 4) AS avg_sim,
  ROUND(MIN(similarity_score)::numeric, 4) AS min_sim,
  ROUND(MAX(similarity_score)::numeric, 4) AS max_sim
FROM pending
GROUP BY 1
ORDER BY MIN(gap_seconds);

-- Incidents with duplicate_flag but no pending duplicate_matches
SELECT
  COUNT(*) FILTER (WHERE i.duplicate_flag) AS flagged_incidents,
  COUNT(*) FILTER (WHERE i.duplicate_flag AND EXISTS (
    SELECT 1 FROM duplicate_matches dm
    WHERE dm.status = 'pending'
      AND (dm.incident_id = i.id OR dm.matched_incident_id = i.id)
  )) AS flagged_with_pending_match,
  COUNT(*) FILTER (WHERE i.duplicate_flag AND NOT EXISTS (
    SELECT 1 FROM duplicate_matches dm
    WHERE dm.status = 'pending'
      AND (dm.incident_id = i.id OR dm.matched_incident_id = i.id)
  )) AS flagged_without_pending_match
FROM incidents i
WHERE i.is_deleted = false;
