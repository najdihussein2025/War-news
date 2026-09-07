-- Recurring extracted village mentions from cross-message, cross-village
-- high-sim pairs (sim>0.7, 1h, 14d) — exclude Nabatiyeh-related aliases already covered.
WITH base AS (
  SELECT i.id, i.raw_message_id, i.village_id, i.condition_id, i.khabar,
         COALESCE(r.message_datetime, r.received_at, i.created_at) AS t,
         r.extraction_result
  FROM incidents i
  LEFT JOIN raw_messages r ON r.id = i.raw_message_id
  WHERE i.is_deleted = false
    AND i.khabar IS NOT NULL
    AND i.village_id IS NOT NULL
    AND i.condition_id IS NOT NULL
    AND COALESCE(r.message_datetime, r.received_at, i.created_at) >= NOW() - INTERVAL '14 days'
),
pairs AS (
  SELECT DISTINCT
    LEAST(a.raw_message_id, b.raw_message_id) AS rm1,
    GREATEST(a.raw_message_id, b.raw_message_id) AS rm2
  FROM base a
  JOIN base b ON a.id < b.id
    AND a.condition_id = b.condition_id
    AND a.village_id <> b.village_id
    AND a.raw_message_id IS DISTINCT FROM b.raw_message_id
    AND ABS(EXTRACT(EPOCH FROM (a.t - b.t))) < 3600
  WHERE word_similarity(a.khabar, b.khabar) > 0.7
),
involved_rms AS (
  SELECT rm1 AS raw_message_id FROM pairs
  UNION
  SELECT rm2 FROM pairs
),
mentions AS (
  SELECT
    r.id AS raw_message_id,
    COALESCE(vr.elem->>'village', v.elem) AS mention,
    vm.elem->>'matched_village_id' AS matched_village_id,
    vm.elem->>'village_match_status' AS match_status,
    vm.elem->>'village_confidence' AS confidence
  FROM involved_rms ir
  JOIN raw_messages r ON r.id = ir.raw_message_id
  LEFT JOIN LATERAL jsonb_array_elements_text(
    COALESCE(r.extraction_result->'village', '[]'::jsonb)
  ) WITH ORDINALITY AS v(elem, ord) ON true
  LEFT JOIN LATERAL jsonb_array_elements(
    COALESCE(r.extraction_result->'village_roles', '[]'::jsonb)
  ) WITH ORDINALITY AS vr(elem, ord) ON vr.ord = v.ord
  LEFT JOIN LATERAL jsonb_array_elements(
    COALESCE(r.match_result->'village_matches', '[]'::jsonb)
  ) WITH ORDINALITY AS vm(elem, ord) ON
    (vm.elem->>'raw_village_text') = COALESCE(vr.elem->>'village', v.elem)
)
SELECT
  mention,
  COUNT(*) AS mention_count,
  COUNT(DISTINCT raw_message_id) AS distinct_messages,
  array_agg(DISTINCT matched_village_id) FILTER (WHERE matched_village_id IS NOT NULL) AS matched_ids,
  array_agg(DISTINCT match_status) FILTER (WHERE match_status IS NOT NULL) AS statuses
FROM mentions
WHERE mention IS NOT NULL
  AND mention <> ''
  -- exclude already-covered Nabatiyeh aliases / names
  AND mention NOT ILIKE '%نبطية%'
  AND mention NOT ILIKE '%مسلخ%'
  AND mention NOT ILIKE '%Nabati%'
GROUP BY mention
ORDER BY distinct_messages DESC, mention_count DESC
LIMIT 40;
