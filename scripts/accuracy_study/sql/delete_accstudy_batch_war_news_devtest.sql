-- Manual cleanup for ACCSTUDY accuracy-study batch on war_news_devtest ONLY.
-- Never run against war_news_dev (production).

BEGIN;

CREATE TEMP TABLE accstudy_incidents AS
SELECT i.id, i.raw_message_id
FROM incidents i
WHERE i.note LIKE 'ACCSTUDY-%'
   OR i.raw_message_id IN (
        SELECT id FROM raw_messages
        WHERE raw_text LIKE '%ACCSTUDY-%'
           OR raw_text LIKE '%NOTE: ACCSTUDY-%'
           OR (raw_payload->>'origin') = 'incident_excel_import'
              AND EXISTS (
                  SELECT 1 FROM incidents i2
                  WHERE i2.raw_message_id = raw_messages.id
                    AND i2.note LIKE 'ACCSTUDY-%'
              )
   );

CREATE TEMP TABLE accstudy_raw AS
SELECT DISTINCT raw_message_id AS id
FROM accstudy_incidents
WHERE raw_message_id IS NOT NULL
UNION
SELECT id
FROM raw_messages
WHERE raw_text LIKE '%ACCSTUDY-%'
   OR raw_text LIKE '%NOTE: ACCSTUDY-%';

DELETE FROM incident_details
WHERE incident_id IN (SELECT id FROM accstudy_incidents);

DELETE FROM incident_updates
WHERE incident_id IN (SELECT id FROM accstudy_incidents);

DELETE FROM duplicate_matches
WHERE incident_id IN (SELECT id FROM accstudy_incidents)
   OR matched_incident_id IN (SELECT id FROM accstudy_incidents)
   OR raw_message_id IN (SELECT id FROM accstudy_raw);

DELETE FROM bulletin_casualty_groups
WHERE raw_message_id IN (SELECT id FROM accstudy_raw);

DELETE FROM incidents
WHERE id IN (SELECT id FROM accstudy_incidents);

DELETE FROM raw_messages
WHERE id IN (SELECT id FROM accstudy_raw);

COMMIT;
