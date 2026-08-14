BEGIN;

CREATE TEMP TABLE cnrs_polling_sources_to_delete ON COMMIT DROP AS
SELECT id, name
FROM sources
WHERE name IN ('CNRS Inspected Posts', 'CNRS Inspected Posts (LLM)');

SELECT 'sources_matched_for_delete' AS metric, COUNT(*) AS count
FROM cnrs_polling_sources_to_delete;

SELECT 'raw_messages_expected_cascade_delete' AS metric, COUNT(*) AS count
FROM raw_messages
WHERE source_id IN (SELECT id FROM cnrs_polling_sources_to_delete);

CREATE TEMP TABLE cnrs_polling_sources_deleted ON COMMIT DROP AS
WITH deleted AS (
    DELETE FROM sources
    WHERE id IN (SELECT id FROM cnrs_polling_sources_to_delete)
    RETURNING id, name
)
SELECT id, name
FROM deleted;

SELECT 'sources_deleted' AS metric, COUNT(*) AS count
FROM cnrs_polling_sources_deleted;

SELECT 'remaining_sources' AS metric, COUNT(*) AS count
FROM sources;

SELECT 'dangling_raw_messages' AS metric, COUNT(*) AS count
FROM raw_messages rm
LEFT JOIN sources s ON s.id = rm.source_id
WHERE s.id IS NULL;

COMMIT;
