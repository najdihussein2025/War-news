-- ========== STEP 1: Headline numbers ==========
SELECT 'total_active_all' AS metric, COUNT(*)::bigint AS n
FROM incidents WHERE is_deleted = false
UNION ALL
SELECT 'total_active_dashboard_scope', COUNT(*)::bigint
FROM incidents i
LEFT JOIN raw_messages r ON r.id = i.raw_message_id
WHERE i.is_deleted = false
  AND (r.id IS NULL OR NOT (r.raw_payload ? 'ocr_text'))
UNION ALL
SELECT 'needs_verification_column', COUNT(*)::bigint
FROM incidents WHERE is_deleted = false AND verification_status = 'needs_verification'
UNION ALL
SELECT 'needs_verification_dashboard_api', COUNT(*)::bigint
FROM incidents i
LEFT JOIN raw_messages r ON r.id = i.raw_message_id
WHERE i.is_deleted = false
  AND (r.id IS NULL OR NOT (r.raw_payload ? 'ocr_text'))
  AND (
    r.match_result->>'any_village_low_confidence' = 'true'
    OR r.match_result->>'village_match_status' = 'matched_low_confidence'
    OR r.match_result->>'condition_match_status' = 'matched_low_confidence'
  )
UNION ALL
SELECT 'possible_duplicates_flag', COUNT(*)::bigint
FROM incidents WHERE is_deleted = false AND duplicate_flag = true
UNION ALL
SELECT 'possible_duplicates_dashboard_scope', COUNT(*)::bigint
FROM incidents i
LEFT JOIN raw_messages r ON r.id = i.raw_message_id
WHERE i.is_deleted = false
  AND (r.id IS NULL OR NOT (r.raw_payload ? 'ocr_text'))
  AND i.duplicate_flag = true;

SELECT verification_status, COUNT(*) AS n
FROM incidents WHERE is_deleted = false
GROUP BY 1 ORDER BY 2 DESC;

-- ========== STEP 2: Column NV condition buckets ==========
WITH nv AS (
  SELECT i.id, i.verification_status, i.duplicate_flag, i.verification_reason,
         r.match_result
  FROM incidents i
  LEFT JOIN raw_messages r ON r.id = i.raw_message_id
  WHERE i.is_deleted = false
    AND i.verification_status = 'needs_verification'
)
SELECT
  CASE
    WHEN match_result->>'condition_match_status' = 'matched' THEN 'condition_matched'
    WHEN match_result->>'condition_match_status' = 'matched_low_confidence' THEN 'condition_low_confidence'
    WHEN match_result->>'condition_match_status' IS NULL OR match_result->>'condition_match_status' = '' THEN 'condition_missing'
    ELSE 'condition_' || COALESCE(match_result->>'condition_match_status','other')
  END AS condition_bucket,
  COUNT(*) AS n
FROM nv
GROUP BY 1 ORDER BY 2 DESC;

-- Village score buckets for column NV
WITH nv AS (
  SELECT i.id, r.match_result
  FROM incidents i
  LEFT JOIN raw_messages r ON r.id = i.raw_message_id
  WHERE i.is_deleted = false AND i.verification_status = 'needs_verification'
),
village_scores AS (
  SELECT
    id,
    (
      SELECT MIN((v->>'village_match_score')::float)
      FROM jsonb_array_elements(COALESCE(match_result->'village_matches','[]'::jsonb)) v
      WHERE COALESCE(v->>'village_role','target') = 'target'
        AND v->>'village_match_score' IS NOT NULL
    ) AS min_target_score,
    match_result->>'village_match_status' AS top_village_status,
    match_result->>'any_village_low_confidence' AS any_low
  FROM nv
)
SELECT
  CASE
    WHEN min_target_score IS NULL AND (top_village_status IS NULL OR top_village_status = '') THEN 'no_village_score'
    WHEN COALESCE(min_target_score, -1) >= 0.6 OR top_village_status = 'matched' THEN 'village_confident_ge_0.6'
    WHEN COALESCE(min_target_score, -1) >= 0.35 OR top_village_status = 'matched_low_confidence' OR any_low = 'true'
      THEN 'village_low_confidence_0.35_0.6'
    ELSE 'village_unmatched_lt_0.35'
  END AS village_bucket,
  COUNT(*) AS n
FROM village_scores
GROUP BY 1 ORDER BY 2 DESC;

-- Drivers overlapping for column needs_verification
WITH nv AS (
  SELECT i.id, i.duplicate_flag, i.verification_reason, r.match_result,
         r.low_confidence_relevance,
         r.filter_result
  FROM incidents i
  LEFT JOIN raw_messages r ON r.id = i.raw_message_id
  WHERE i.is_deleted = false AND i.verification_status = 'needs_verification'
)
SELECT
  COUNT(*) AS total_nv_column,
  COUNT(*) FILTER (WHERE duplicate_flag) AS driven_by_duplicate_flag,
  COUNT(*) FILTER (WHERE match_result->>'condition_match_status' IS DISTINCT FROM 'matched') AS condition_not_matched,
  COUNT(*) FILTER (WHERE match_result->>'any_village_low_confidence' = 'true'
    OR match_result->>'village_match_status' = 'matched_low_confidence') AS village_low_conf_flag,
  COUNT(*) FILTER (WHERE COALESCE(low_confidence_relevance, false)
    OR COALESCE((filter_result->>'needs_review')::boolean, false)) AS relevance_needs_review,
  COUNT(*) FILTER (WHERE verification_reason ILIKE '%casualty%' OR verification_reason ILIKE '%gender%' OR verification_reason ILIKE '%transition%') AS casualty_or_gender_reason,
  COUNT(*) FILTER (WHERE verification_reason IS NOT NULL AND verification_reason <> '') AS has_verification_reason
FROM nv;

SELECT COALESCE(NULLIF(verification_reason,''), '(null)') AS reason, COUNT(*) AS n
FROM incidents
WHERE is_deleted = false AND verification_status = 'needs_verification'
GROUP BY 1 ORDER BY 2 DESC LIMIT 20;

-- Dashboard API NV breakdown
WITH dash AS (
  SELECT i.id, r.match_result
  FROM incidents i
  LEFT JOIN raw_messages r ON r.id = i.raw_message_id
  WHERE i.is_deleted = false
    AND (r.id IS NULL OR NOT (r.raw_payload ? 'ocr_text'))
    AND (
      r.match_result->>'any_village_low_confidence' = 'true'
      OR r.match_result->>'village_match_status' = 'matched_low_confidence'
      OR r.match_result->>'condition_match_status' = 'matched_low_confidence'
    )
)
SELECT
  COUNT(*) AS dash_nv_total,
  COUNT(*) FILTER (WHERE match_result->>'any_village_low_confidence' = 'true') AS any_village_low,
  COUNT(*) FILTER (WHERE match_result->>'village_match_status' = 'matched_low_confidence') AS village_status_low,
  COUNT(*) FILTER (WHERE match_result->>'condition_match_status' = 'matched_low_confidence') AS condition_low,
  COUNT(*) FILTER (WHERE match_result->>'condition_match_status' = 'matched_low_confidence'
    AND NOT (COALESCE(match_result->>'any_village_low_confidence','') = 'true'
             OR match_result->>'village_match_status' = 'matched_low_confidence')) AS condition_only,
  COUNT(*) FILTER (WHERE (COALESCE(match_result->>'any_village_low_confidence','') = 'true'
             OR match_result->>'village_match_status' = 'matched_low_confidence')
    AND match_result->>'condition_match_status' IS DISTINCT FROM 'matched_low_confidence') AS village_only,
  COUNT(*) FILTER (WHERE (COALESCE(match_result->>'any_village_low_confidence','') = 'true'
             OR match_result->>'village_match_status' = 'matched_low_confidence')
    AND match_result->>'condition_match_status' = 'matched_low_confidence') AS both
FROM dash;
