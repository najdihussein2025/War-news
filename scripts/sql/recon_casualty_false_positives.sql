-- Recon (read-only): incidents matched by the casualties filter that carry no real count.
--
-- Mirrors IncidentRepositoryListQueryMixin when has_casualties=true
-- (app/news/repositories/incident_repository_listing.py):
--   total_deaths > 0 OR total_injuries > 0 OR casualty_status = 'count_missing'
--   OR visible open count_missing flag OR visible open aggregate_no_breakdown flag.
-- Then keeps only rows where no death/injury count is > 0 in totals, male, female or children.
--
-- SELECT only. Do not convert into DML.

WITH visible_flags AS (
    SELECT f.incident_id, f.reason_code
    FROM incident_verification_flags f
    WHERE f.status = 'open'
      AND f.flag_type = 'casualty_check'
      AND (f.visible_after IS NULL OR f.visible_after <= now())
),
matched AS (
    SELECT i.id
    FROM incidents i
    WHERE i.is_deleted IS FALSE
      AND (
            COALESCE(i.total_deaths, 0) > 0
         OR COALESCE(i.total_injuries, 0) > 0
         OR i.casualty_status = 'count_missing'
         OR EXISTS (SELECT 1 FROM visible_flags v WHERE v.incident_id = i.id AND v.reason_code = 'count_missing')
         OR EXISTS (SELECT 1 FROM visible_flags v WHERE v.incident_id = i.id AND v.reason_code = 'aggregate_no_breakdown')
      )
)
SELECT
    i.id                                AS incident_id,
    vil.ref_name_en                     AS village,
    i.created_at                        AS created_at,
    i.verification_status               AS verification_status,
    i.casualty_status                   AS casualty_status,
    i.total_deaths                      AS total_deaths,
    i.total_injuries                    AS total_injuries,
    d.male_d, d.male_i,
    d.female_d, d.female_i,
    d.children_d, d.children_i,
    (SELECT string_agg(DISTINCT v.reason_code, ',')
       FROM visible_flags v WHERE v.incident_id = i.id) AS open_casualty_flag_reasons,
    LEFT(REGEXP_REPLACE(COALESCE(rm.raw_text, ''), '\s+', ' ', 'g'), 300) AS source_text_snippet
FROM matched m
JOIN incidents i                ON i.id = m.id
LEFT JOIN villages vil          ON vil.id = i.village_id
LEFT JOIN incident_details d    ON d.incident_id = i.id
LEFT JOIN raw_messages rm       ON rm.id = i.raw_message_id
WHERE COALESCE(i.total_deaths, 0) = 0
  AND COALESCE(i.total_injuries, 0) = 0
  AND COALESCE(d.male_d, 0) = 0
  AND COALESCE(d.male_i, 0) = 0
  AND COALESCE(d.female_d, 0) = 0
  AND COALESCE(d.female_i, 0) = 0
  AND COALESCE(d.children_d, 0) = 0
  AND COALESCE(d.children_i, 0) = 0
ORDER BY i.created_at DESC;
