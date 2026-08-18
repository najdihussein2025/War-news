"""Periodic check: pre-dedup duplicates whose original never materialized."""

PRE_DEDUP_ORPHAN_QUERY = """
-- Pre-dedup orphan monitor
-- Rows marked duplicate before extraction whose canonical message never
-- reached a materialized incident (or failed downstream entirely).
SELECT
    dup.id AS duplicate_message_id,
    dup.duplicate_of_id AS original_message_id,
    dup.message_datetime AS duplicate_message_datetime,
    orig.status AS original_status,
    orig.error_message AS original_error,
    orig.extraction_result IS NOT NULL AS original_has_extraction,
    orig.match_result IS NOT NULL AS original_has_match,
    EXISTS (
        SELECT 1
        FROM incidents i
        WHERE i.raw_message_id = orig.id
          AND i.is_deleted IS FALSE
    ) AS original_materialized
FROM raw_messages dup
JOIN raw_messages orig ON orig.id = dup.duplicate_of_id
WHERE dup.status = 'duplicate'
  AND dup.duplicate_of_id IS NOT NULL
  AND (
        orig.status <> 'parsed'
        OR NOT EXISTS (
            SELECT 1
            FROM incidents i
            WHERE i.raw_message_id = orig.id
              AND i.is_deleted IS FALSE
        )
      )
ORDER BY dup.id DESC;
"""

if __name__ == "__main__":
    print(PRE_DEDUP_ORPHAN_QUERY.strip())
