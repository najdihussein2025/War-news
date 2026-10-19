-- Recon (read-only): how many incidents would go to manual check, and why.
--
-- Pre-Phase-3 sizing for the "casualties mentioned, no exact number" queue.
-- Candidates are incidents with no real count (same rule as
-- app/news/repositories/reported_casualties.py) whose stored casualty status is
-- count_missing for deaths, injuries or overall.
--
-- Bucket, from the stored evidence sentence:
--   number_in_text_not_stored : evidence contains a digit (Arabic or Latin) -> extraction miss
--   wording_only              : evidence has no digit (e.g. «وقوع إصابات», «سقوط ضحايا»)
--
-- SELECT only. Run manually. Query 1 = sizes, query 2 = real examples per bucket.

WITH no_count AS (
    SELECT i.id, i.created_at, i.verification_status, i.verification_reason,
           i.casualty_status, i.casualty_deaths_status, i.casualty_injuries_status,
           i.casualty_status_evidence, i.village_id, i.raw_message_id
    FROM incidents i
    LEFT JOIN incident_details d ON d.incident_id = i.id
    WHERE i.is_deleted IS FALSE
      AND COALESCE(i.total_deaths, 0) = 0 AND COALESCE(i.total_injuries, 0) = 0
      AND COALESCE(d.male_d, 0) = 0 AND COALESCE(d.male_i, 0) = 0
      AND COALESCE(d.female_d, 0) = 0 AND COALESCE(d.female_i, 0) = 0
      AND COALESCE(d.children_d, 0) = 0 AND COALESCE(d.children_i, 0) = 0
      AND 'count_missing' IN (
            COALESCE(i.casualty_status, ''),
            COALESCE(i.casualty_deaths_status, ''),
            COALESCE(i.casualty_injuries_status, ''))
),
bucketed AS (
    SELECT n.*,
           CASE WHEN n.casualty_status_evidence ~ '[0-9٠-٩]'
                THEN 'number_in_text_not_stored' ELSE 'wording_only' END AS bucket
    FROM no_count n
)
-- Query 1: sizes (total and still-unreviewed)
SELECT bucket,
       COUNT(*)                                                         AS incidents,
       COUNT(*) FILTER (WHERE verification_status <> 'needs_verification') AS not_yet_in_verification,
       COUNT(DISTINCT raw_message_id)                                   AS distinct_messages,
       MIN(created_at)::date                                            AS oldest,
       MAX(created_at)::date                                            AS newest
FROM bucketed
GROUP BY bucket
ORDER BY bucket;

-- Query 2: real examples (run separately, using the same WITH block above)
-- SELECT b.bucket, b.id AS incident_id, v.ref_name_en AS village, b.created_at,
--        b.verification_status, b.casualty_status_evidence,
--        LEFT(REGEXP_REPLACE(COALESCE(rm.raw_text, ''), '\s+', ' ', 'g'), 300) AS source_text_snippet
-- FROM bucketed b
-- LEFT JOIN villages v ON v.id = b.village_id
-- LEFT JOIN raw_messages rm ON rm.id = b.raw_message_id
-- ORDER BY b.bucket, b.created_at DESC
-- LIMIT 40;
