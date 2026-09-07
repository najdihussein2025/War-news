-- Step 4: pairwise pre-extraction word_similarity among maslakh cluster
-- (same metric as pre_extraction_dedup.py)
WITH msgs AS (
  SELECT id, source_id, status, duplicate_of_id, message_datetime, received_at,
         regexp_replace(raw_text, E'[\n\r]+', ' ', 'g') AS raw_text
  FROM raw_messages
  WHERE id IN (8541,8543,8547,8550,8553,8554,8557,8558,8561,8563,8564,8565)
)
SELECT a.id AS id_a, b.id AS id_b,
       a.status AS status_a, b.status AS status_b,
       a.duplicate_of_id AS dup_a, b.duplicate_of_id AS dup_b,
       round(word_similarity(a.raw_text, b.raw_text)::numeric, 4) AS word_sim_ab,
       round(word_similarity(b.raw_text, a.raw_text)::numeric, 4) AS word_sim_ba,
       LEFT(a.raw_text, 70) AS text_a,
       LEFT(b.raw_text, 70) AS text_b
FROM msgs a
JOIN msgs b ON a.id < b.id
ORDER BY GREATEST(word_similarity(a.raw_text, b.raw_text), word_similarity(b.raw_text, a.raw_text)) DESC;
