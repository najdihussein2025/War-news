-- Village match status distribution from village_matches array for NV column
WITH nv AS (
  SELECT i.id, r.match_result
  FROM incidents i
  LEFT JOIN raw_messages r ON r.id = i.raw_message_id
  WHERE i.is_deleted = false AND i.verification_status = 'needs_verification'
),
expanded AS (
  SELECT
    nv.id,
    v->>'village_match_status' AS st,
    NULLIF(v->>'confidence','')::float AS confidence,
    NULLIF(v->>'village_match_score','')::float AS score_alt,
    COALESCE(v->>'village_role','target') AS role,
    match_result->>'any_village_low_confidence' AS any_low,
    match_result->>'condition_match_status' AS cond
  FROM nv
  LEFT JOIN LATERAL jsonb_array_elements(COALESCE(match_result->'village_matches','[]'::jsonb)) v ON true
)
SELECT role, st,
  CASE
    WHEN COALESCE(confidence, score_alt) IS NULL THEN 'no_score'
    WHEN COALESCE(confidence, score_alt) >= 0.6 THEN 'ge_0.6'
    WHEN COALESCE(confidence, score_alt) >= 0.35 THEN '0.35_0.6'
    ELSE 'lt_0.35'
  END AS score_bucket,
  COUNT(*) AS n
FROM expanded
GROUP BY 1,2,3
ORDER BY 1,4 DESC;

-- Per-incident primary target village bucket for NV
WITH nv AS (
  SELECT i.id, r.match_result,
         match_result->>'any_village_low_confidence' AS any_low,
         match_result->>'condition_match_status' AS cond
  FROM incidents i
  LEFT JOIN raw_messages r ON r.id = i.raw_message_id
  WHERE i.is_deleted = false AND i.verification_status = 'needs_verification'
),
per AS (
  SELECT
    id, any_low, cond,
    (
      SELECT v->>'village_match_status'
      FROM jsonb_array_elements(COALESCE(match_result->'village_matches','[]'::jsonb)) v
      WHERE COALESCE(v->>'village_role','target') = 'target'
      ORDER BY COALESCE(NULLIF(v->>'confidence','')::float, 0) DESC
      LIMIT 1
    ) AS best_status,
    (
      SELECT COALESCE(NULLIF(v->>'confidence','')::float, NULLIF(v->>'village_match_score','')::float)
      FROM jsonb_array_elements(COALESCE(match_result->'village_matches','[]'::jsonb)) v
      WHERE COALESCE(v->>'village_role','target') = 'target'
      ORDER BY COALESCE(NULLIF(v->>'confidence','')::float, 0) DESC
      LIMIT 1
    ) AS best_score,
    jsonb_array_length(COALESCE(match_result->'village_matches','[]'::jsonb)) AS n_matches
  FROM nv
)
SELECT
  CASE
    WHEN n_matches = 0 OR best_status IS NULL THEN 'no_target_village'
    WHEN best_score >= 0.6 OR best_status = 'matched' THEN 'village_confident_ge_0.6'
    WHEN best_score >= 0.35 OR best_status = 'matched_low_confidence' THEN 'village_low_confidence_0.35_0.6'
    ELSE 'village_unmatched_lt_0.35'
  END AS village_bucket,
  COUNT(*) AS n
FROM per
GROUP BY 1 ORDER BY 2 DESC;

-- Cross-tab reason drivers for column NV (mutually exclusive primary reason priority)
WITH nv AS (
  SELECT i.id, i.duplicate_flag, r.match_result
  FROM incidents i
  LEFT JOIN raw_messages r ON r.id = i.raw_message_id
  WHERE i.is_deleted = false AND i.verification_status = 'needs_verification'
),
classified AS (
  SELECT
    id,
    CASE
      WHEN EXISTS (
        SELECT 1 FROM jsonb_array_elements(COALESCE(match_result->'village_matches','[]'::jsonb)) v
        WHERE COALESCE(v->>'village_role','target') = 'target'
          AND v->>'village_match_status' IS DISTINCT FROM 'matched'
      ) OR match_result->>'any_village_low_confidence' = 'true'
        THEN 'village_not_confident'
      WHEN match_result->>'condition_match_status' IS DISTINCT FROM 'matched'
        THEN 'condition_not_confident'
      WHEN duplicate_flag THEN 'duplicate_flag_only'
      ELSE 'other_or_stale'
    END AS primary_reason,
    duplicate_flag,
    match_result->>'condition_match_status' AS cond,
    match_result->>'any_village_low_confidence' AS any_low
  FROM nv
)
SELECT primary_reason, COUNT(*) AS n,
  COUNT(*) FILTER (WHERE duplicate_flag) AS also_dup_flag
FROM classified
GROUP BY 1 ORDER BY 2 DESC;

-- Overlap matrix
WITH nv AS (
  SELECT i.id, i.duplicate_flag,
    (match_result->>'any_village_low_confidence' = 'true'
      OR EXISTS (
        SELECT 1 FROM jsonb_array_elements(COALESCE(match_result->'village_matches','[]'::jsonb)) v
        WHERE COALESCE(v->>'village_role','target') = 'target'
          AND v->>'village_match_status' IS DISTINCT FROM 'matched'
      )) AS village_issue,
    (match_result->>'condition_match_status' IS DISTINCT FROM 'matched') AS condition_issue
  FROM incidents i
  LEFT JOIN raw_messages r ON r.id = i.raw_message_id
  WHERE i.is_deleted = false AND i.verification_status = 'needs_verification'
)
SELECT
  village_issue, condition_issue, duplicate_flag, COUNT(*) AS n
FROM nv
GROUP BY 1,2,3
ORDER BY 4 DESC;

-- Dashboard NV village buckets
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
),
per AS (
  SELECT id,
    match_result->>'any_village_low_confidence' AS any_low,
    match_result->>'condition_match_status' AS cond,
    (
      SELECT COALESCE(NULLIF(v->>'confidence','')::float, NULLIF(v->>'village_match_score','')::float)
      FROM jsonb_array_elements(COALESCE(match_result->'village_matches','[]'::jsonb)) v
      WHERE COALESCE(v->>'village_role','target') = 'target'
      ORDER BY COALESCE(NULLIF(v->>'confidence','')::float, 0) DESC
      LIMIT 1
    ) AS best_score,
    (
      SELECT v->>'village_match_status'
      FROM jsonb_array_elements(COALESCE(match_result->'village_matches','[]'::jsonb)) v
      WHERE COALESCE(v->>'village_role','target') = 'target'
      ORDER BY COALESCE(NULLIF(v->>'confidence','')::float, 0) DESC
      LIMIT 1
    ) AS best_status
  FROM dash
)
SELECT
  CASE
    WHEN best_score >= 0.6 OR best_status = 'matched' THEN 'village_confident_ge_0.6'
    WHEN best_score >= 0.35 OR best_status = 'matched_low_confidence' OR any_low = 'true'
      THEN 'village_low_confidence_0.35_0.6'
    WHEN best_status IS NULL THEN 'no_target_village'
    ELSE 'village_unmatched_lt_0.35'
  END AS village_bucket,
  cond AS condition_status,
  COUNT(*) AS n
FROM per
GROUP BY 1,2
ORDER BY 3 DESC;
