-- Part 3 samples
WITH scope AS (
  SELECT i.id, i.verification_status, i.duplicate_flag, i.created_at,
         COALESCE(v.ref_name_en, v.cad_name) AS village,
         c.action_en AS condition,
         r.match_result,
         (
           r.match_result->>'any_village_low_confidence' = 'true'
           OR r.match_result->>'village_match_status' = 'matched_low_confidence'
           OR r.match_result->>'condition_match_status' = 'matched_low_confidence'
         ) AS api_nv
  FROM incidents i
  LEFT JOIN raw_messages r ON r.id = i.raw_message_id
  LEFT JOIN villages v ON v.id = i.village_id
  LEFT JOIN conditions c ON c.id = i.condition_id
  WHERE i.is_deleted = false
    AND (r.id IS NULL OR NOT (r.raw_payload ? 'ocr_text'))
)
SELECT 'column_only' AS bucket, LEFT(id::text,8) AS id8, id::text AS full_id,
  verification_status, duplicate_flag, village, condition,
  match_result->>'any_village_low_confidence' AS any_low,
  match_result->>'condition_match_status' AS cond,
  (
    SELECT string_agg(
      COALESCE(v->>'village_role','?') || ':' || COALESCE(v->>'village_match_status','?'),
      ', '
    )
    FROM jsonb_array_elements(COALESCE(match_result->'village_matches','[]'::jsonb)) v
  ) AS village_statuses
FROM scope
WHERE verification_status='needs_verification' AND NOT COALESCE(api_nv,false)
ORDER BY duplicate_flag DESC, created_at DESC
LIMIT 6;

WITH scope AS (
  SELECT i.id, i.verification_status, i.duplicate_flag, i.created_at,
         COALESCE(v.ref_name_en, v.cad_name) AS village,
         c.action_en AS condition,
         r.match_result,
         (
           r.match_result->>'any_village_low_confidence' = 'true'
           OR r.match_result->>'village_match_status' = 'matched_low_confidence'
           OR r.match_result->>'condition_match_status' = 'matched_low_confidence'
         ) AS api_nv
  FROM incidents i
  LEFT JOIN raw_messages r ON r.id = i.raw_message_id
  LEFT JOIN villages v ON v.id = i.village_id
  LEFT JOIN conditions c ON c.id = i.condition_id
  WHERE i.is_deleted = false
    AND (r.id IS NULL OR NOT (r.raw_payload ? 'ocr_text'))
)
SELECT 'api_only' AS bucket, LEFT(id::text,8) AS id8, id::text AS full_id,
  verification_status, duplicate_flag, village, condition,
  match_result->>'any_village_low_confidence' AS any_low,
  match_result->>'condition_match_status' AS cond,
  NULLIF(match_result->>'condition_confidence','')::float AS cond_conf
FROM scope
WHERE verification_status IS DISTINCT FROM 'needs_verification' AND COALESCE(api_nv,false)
ORDER BY created_at DESC
LIMIT 6;

-- Why api_only can be auto_processed with any_low true: check if targets are all matched
WITH scope AS (
  SELECT i.id, r.match_result
  FROM incidents i
  LEFT JOIN raw_messages r ON r.id = i.raw_message_id
  WHERE i.is_deleted = false
    AND i.verification_status = 'auto_processed'
    AND (
      r.match_result->>'any_village_low_confidence' = 'true'
      OR r.match_result->>'condition_match_status' = 'matched_low_confidence'
    )
)
SELECT
  COUNT(*) AS api_onlyish,
  COUNT(*) FILTER (WHERE EXISTS (
    SELECT 1 FROM jsonb_array_elements(COALESCE(match_result->'village_matches','[]'::jsonb)) v
    WHERE COALESCE(v->>'village_role','target')='target'
      AND v->>'village_match_status' = 'matched_low_confidence'
  )) AS has_target_low,
  COUNT(*) FILTER (WHERE EXISTS (
    SELECT 1 FROM jsonb_array_elements(COALESCE(match_result->'village_matches','[]'::jsonb)) v
    WHERE COALESCE(v->>'village_role','target') <> 'target'
      AND v->>'village_match_status' = 'matched_low_confidence'
  )) AS has_origin_low_only,
  COUNT(*) FILTER (WHERE match_result->>'condition_match_status'='matched_low_confidence') AS cond_low
FROM scope;
