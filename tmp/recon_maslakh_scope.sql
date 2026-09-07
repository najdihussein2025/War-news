-- Step 5: cross-village high text-similarity incident pairs (1h window)
-- Use word_similarity on khabar as in the prompt. Cap scan for practicality:
-- recent backlog / last 14 days if volume is large.
SELECT a.id AS id_a, b.id AS id_b,
       a.village_id AS vid_a, b.village_id AS vid_b,
       va.acs_name AS village_a, vb.acs_name AS village_b,
       a.condition_id AS cid_a, b.condition_id AS cid_b,
       a.event_date AS t_a, b.event_date AS t_b,
       ROUND(ABS(EXTRACT(EPOCH FROM (a.event_date - b.event_date)))::numeric, 0) AS gap_sec,
       round(word_similarity(a.khabar, b.khabar)::numeric, 4) AS sim,
       LEFT(a.khabar, 90) AS khabar_a,
       LEFT(b.khabar, 90) AS khabar_b
FROM incidents a
JOIN incidents b ON a.id < b.id
  AND a.condition_id = b.condition_id
  AND a.village_id IS DISTINCT FROM b.village_id
  AND ABS(EXTRACT(EPOCH FROM (a.event_date - b.event_date))) < 3600
JOIN villages va ON va.id = a.village_id
JOIN villages vb ON vb.id = b.village_id
WHERE a.is_deleted = false AND b.is_deleted = false
  AND a.khabar IS NOT NULL AND b.khabar IS NOT NULL
  AND a.event_date >= NOW() - INTERVAL '14 days'
  AND word_similarity(a.khabar, b.khabar) > 0.4
ORDER BY sim DESC
LIMIT 50;
