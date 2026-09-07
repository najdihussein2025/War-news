-- Part 1d: pre-dedup threshold evidence
-- A) Same-event Nabatiyeh/maslakh cluster pairwise word_similarity (source 3)
WITH msgs AS (
  SELECT id, raw_text
  FROM raw_messages
  WHERE id IN (8541,8543,8547,8550,8553,8554,8557,8558,8561,8563,8564,8565)
)
SELECT
  COUNT(*) AS pair_count,
  COUNT(*) FILTER (WHERE GREATEST(word_similarity(a.raw_text,b.raw_text), word_similarity(b.raw_text,a.raw_text)) >= 0.92) AS ge_0_92,
  COUNT(*) FILTER (WHERE GREATEST(word_similarity(a.raw_text,b.raw_text), word_similarity(b.raw_text,a.raw_text)) >= 0.87) AS ge_0_87,
  COUNT(*) FILTER (WHERE GREATEST(word_similarity(a.raw_text,b.raw_text), word_similarity(b.raw_text,a.raw_text)) >= 0.85) AS ge_0_85,
  COUNT(*) FILTER (WHERE GREATEST(word_similarity(a.raw_text,b.raw_text), word_similarity(b.raw_text,a.raw_text)) >= 0.80) AS ge_0_80,
  round(AVG(GREATEST(word_similarity(a.raw_text,b.raw_text), word_similarity(b.raw_text,a.raw_text)))::numeric, 4) AS avg_max_sim,
  round(MAX(GREATEST(word_similarity(a.raw_text,b.raw_text), word_similarity(b.raw_text,a.raw_text)))::numeric, 4) AS max_sim
FROM msgs a JOIN msgs b ON a.id < b.id;

-- B) Proxy different-event: same source, |Δreceived| < 1h, already-materialized
-- pairs where BOTH khabar/raw mention clearly different primary villages
-- Use confirmed distinct via different condition_id on linked incidents when available.
WITH recent AS (
  SELECT r.id, r.source_id, r.raw_text, r.received_at,
         i.condition_id, i.village_id
  FROM raw_messages r
  JOIN incidents i ON i.raw_message_id = r.id AND i.is_deleted = false
  WHERE r.source_id = 3
    AND r.received_at >= NOW() - INTERVAL '14 days'
    AND r.raw_text IS NOT NULL
    AND r.status = 'materialized'
),
pairs AS (
  SELECT
    GREATEST(word_similarity(a.raw_text, b.raw_text), word_similarity(b.raw_text, a.raw_text)) AS sim,
    (a.condition_id IS DISTINCT FROM b.condition_id) AS different_condition,
    (a.village_id IS DISTINCT FROM b.village_id) AS different_village
  FROM recent a
  JOIN recent b ON a.id < b.id
    AND a.source_id = b.source_id
    AND ABS(EXTRACT(EPOCH FROM (a.received_at - b.received_at))) < 3600
  WHERE word_similarity(a.raw_text, b.raw_text) > 0.75
     OR word_similarity(b.raw_text, a.raw_text) > 0.75
)
SELECT
  COUNT(*) FILTER (WHERE different_condition) AS diff_condition_pairs_ge_0_75,
  COUNT(*) FILTER (WHERE different_condition AND sim >= 0.85) AS diff_cond_ge_0_85,
  COUNT(*) FILTER (WHERE different_condition AND sim >= 0.87) AS diff_cond_ge_0_87,
  COUNT(*) FILTER (WHERE different_condition AND sim >= 0.92) AS diff_cond_ge_0_92,
  COUNT(*) FILTER (WHERE NOT different_condition AND different_village AND sim >= 0.85) AS same_cond_diff_vill_ge_0_85,
  COUNT(*) FILTER (WHERE NOT different_condition AND different_village AND sim >= 0.87) AS same_cond_diff_vill_ge_0_87,
  COUNT(*) FILTER (WHERE NOT different_condition AND different_village AND sim >= 0.92) AS same_cond_diff_vill_ge_0_92
FROM pairs;
