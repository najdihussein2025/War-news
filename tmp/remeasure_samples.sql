-- Samples: all 4 post-Phase1 pending pairs + 6 near-threshold historical
WITH pending AS (
  SELECT
    dm.id AS match_id,
    dm.incident_id,
    dm.matched_incident_id,
    dm.similarity_score,
    dm.created_at AS match_created_at,
    (dm.created_at >= TIMESTAMPTZ '2026-09-07 12:51:07+03') AS created_after_phase1,
    COALESCE(v1.ref_name_en, v1.cad_name) AS village1,
    COALESCE(v2.ref_name_en, v2.cad_name) AS village2,
    c1.action_en AS condition1,
    c2.action_en AS condition2,
    i1.village_id AS vid1, i2.village_id AS vid2,
    i1.condition_id AS cid1, i2.condition_id AS cid2,
    COALESCE(r1.message_datetime, r1.received_at, i1.created_at) AS t1,
    COALESCE(r2.message_datetime, r2.received_at, i2.created_at) AS t2,
    ABS(EXTRACT(EPOCH FROM (
      COALESCE(r1.message_datetime, r1.received_at, i1.created_at)
      - COALESCE(r2.message_datetime, r2.received_at, i2.created_at)
    ))) AS gap_seconds,
    LEFT(regexp_replace(COALESCE(r1.raw_text,''), E'[\n\r]+', ' ', 'g'), 220) AS text1,
    LEFT(regexp_replace(COALESCE(r2.raw_text,''), E'[\n\r]+', ' ', 'g'), 220) AS text2,
    i1.total_deaths AS k1, i1.total_injuries AS inj1,
    i2.total_deaths AS k2, i2.total_injuries AS inj2
  FROM duplicate_matches dm
  JOIN incidents i1 ON i1.id = dm.incident_id
  JOIN incidents i2 ON i2.id = dm.matched_incident_id
  LEFT JOIN raw_messages r1 ON r1.id = i1.raw_message_id
  LEFT JOIN raw_messages r2 ON r2.id = i2.raw_message_id
  LEFT JOIN villages v1 ON v1.id = i1.village_id
  LEFT JOIN villages v2 ON v2.id = i2.village_id
  LEFT JOIN conditions c1 ON c1.id = i1.condition_id
  LEFT JOIN conditions c2 ON c2.id = i2.condition_id
  WHERE dm.status = 'pending' AND dm.matched_incident_id IS NOT NULL
),
post AS (
  SELECT * FROM pending WHERE created_after_phase1
),
hist AS (
  SELECT * FROM pending WHERE NOT created_after_phase1
  ORDER BY
    CASE
      WHEN gap_seconds <= 21600 AND similarity_score BETWEEN 0.65 AND 0.86 THEN 0
      WHEN gap_seconds > 21600 THEN 2
      ELSE 1
    END,
    ABS(similarity_score - 0.80),
    match_created_at DESC
  LIMIT 6
)
SELECT
  match_id,
  LEFT(incident_id::text, 8) AS inc_a,
  LEFT(matched_incident_id::text, 8) AS inc_b,
  incident_id::text AS incident_id_full,
  matched_incident_id::text AS matched_incident_id_full,
  ROUND(similarity_score::numeric, 4) AS sim,
  ROUND((gap_seconds/60.0)::numeric, 1) AS gap_min,
  CASE
    WHEN gap_seconds <= 120 THEN 'le_2min'
    WHEN gap_seconds <= 1800 THEN 'le_30min'
    WHEN gap_seconds <= 21600 THEN 'le_6h'
    ELSE 'gt_6h'
  END AS gap_bucket,
  created_after_phase1 AS post_p1,
  village1, village2,
  (vid1 IS NOT DISTINCT FROM vid2) AS same_village_id,
  condition1, condition2,
  (cid1 IS NOT DISTINCT FROM cid2) AS same_condition_id,
  k1, inj1, k2, inj2,
  match_created_at,
  text1, text2
FROM (
  SELECT * FROM post
  UNION ALL
  SELECT * FROM hist
) s
ORDER BY post_p1 DESC, gap_seconds ASC, sim DESC;
