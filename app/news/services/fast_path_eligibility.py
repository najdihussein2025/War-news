from __future__ import annotations

from typing import Any

from sqlalchemy import TextClause, text

from app.news.models import MessageStatus

ELIGIBLE_MATCH_STATUSES = frozenset({"matched", "matched_low_confidence"})
AIR_VIOLATION_CONDITION_IDS = frozenset({35, 36, 38, 45})

ERROR_AIR_VIOLATION = "fast_path: routed to air_violations; not an incident"
ERROR_UNMATCHED_CONDITION = "fast_path: unmatched or missing condition"
ERROR_NO_VILLAGE = "fast_path: no materializable village match"
ERROR_EXACT_HASH = "fast_path: exact hash already materialized; no new incident"
ERROR_UNMATERIALIZABLE = "fast_path: permanently unmaterializable"

# Correlated to raw_messages in claim/update statements. Avoids SQLAlchemy `?`
# bind placeholder by using jsonb_typeof instead of the jsonb `?` operator.
FAST_PATH_MATERIALIZABLE_SQL = """
(
  (raw_messages.match_result->>'condition_match_status') IN (
    'matched', 'matched_low_confidence'
  )
  AND (raw_messages.match_result->>'matched_condition_id') ~ '^[0-9]+$'
  AND (raw_messages.match_result->>'matched_condition_id')::int NOT IN (35, 36, 38, 45)
  AND (
    (
      jsonb_typeof(raw_messages.match_result->'village_matches') = 'array'
      AND EXISTS (
        SELECT 1
        FROM jsonb_array_elements(
          COALESCE(raw_messages.match_result->'village_matches', '[]'::jsonb)
        ) AS village(value)
        WHERE village.value->>'village_match_status' IN (
          'matched', 'matched_low_confidence'
        )
          AND (village.value->>'matched_village_id') ~ '^[0-9]+$'
      )
    )
    OR (
      raw_messages.match_result->'village_matches' IS NULL
      AND (raw_messages.match_result->>'village_match_status') IN (
        'matched', 'matched_low_confidence'
      )
      AND (raw_messages.match_result->>'matched_village_id') ~ '^[0-9]+$'
    )
  )
)
"""


def fast_path_materializable_clause() -> TextClause:
    return text(FAST_PATH_MATERIALIZABLE_SQL)


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _normalized_village_matches(match_result: dict[str, Any]) -> list[dict[str, Any]]:
    if "village_matches" in match_result:
        villages = match_result.get("village_matches") or []
        return [entry for entry in villages if isinstance(entry, dict)]
    return [
        {
            "matched_village_id": match_result.get("matched_village_id"),
            "village_match_status": match_result.get(
                "village_match_status", "unmatched"
            ),
        }
    ]


def has_materializable_village(match_result: dict[str, Any]) -> bool:
    for village in _normalized_village_matches(match_result):
        if village.get("village_match_status") not in ELIGIBLE_MATCH_STATUSES:
            continue
        if _optional_int(village.get("matched_village_id")) is None:
            continue
        return True
    return False


def permanent_ineligibility_reason(
    match_result: dict[str, Any] | None,
) -> str | None:
    """Return a terminal error reason, or None if the match can still materialize."""
    if not match_result:
        return ERROR_UNMATCHED_CONDITION

    condition_status = match_result.get("condition_match_status")
    if condition_status not in ELIGIBLE_MATCH_STATUSES:
        return ERROR_UNMATCHED_CONDITION
    condition_id = _optional_int(match_result.get("matched_condition_id"))
    if condition_id is None:
        return ERROR_UNMATCHED_CONDITION
    if condition_id in AIR_VIOLATION_CONDITION_IDS:
        return ERROR_AIR_VIOLATION
    if not has_materializable_village(match_result):
        return ERROR_NO_VILLAGE
    return None


def ineligible_fast_path_update_sql() -> TextClause:
    return text(
        f"""
        UPDATE raw_messages
        SET
            status = CAST(:error_status AS message_status),
            error_message = CASE
                WHEN (raw_messages.match_result->>'matched_condition_id') ~ '^[0-9]+$'
                     AND (raw_messages.match_result->>'matched_condition_id')::int
                         IN (35, 36, 38, 45)
                    THEN :air_violation
                WHEN (raw_messages.match_result->>'condition_match_status') NOT IN (
                        'matched', 'matched_low_confidence'
                     )
                     OR (raw_messages.match_result->>'matched_condition_id') IS NULL
                     OR NOT (
                        (raw_messages.match_result->>'matched_condition_id') ~ '^[0-9]+$'
                     )
                    THEN :unmatched_condition
                ELSE :no_village
            END
        WHERE raw_messages.status = CAST(:parsed_status AS message_status)
          AND raw_messages.duplicate_of_id IS NULL
          AND raw_messages.match_result IS NOT NULL
          AND raw_messages.extraction_result IS NOT NULL
          AND NOT EXISTS (
                SELECT 1
                FROM incidents
                WHERE incidents.raw_message_id = raw_messages.id
                  AND incidents.is_deleted = false
          )
          AND NOT ({FAST_PATH_MATERIALIZABLE_SQL})
        """
    ).bindparams(
        error_status=MessageStatus.error.value,
        parsed_status=MessageStatus.parsed.value,
        air_violation=ERROR_AIR_VIOLATION,
        unmatched_condition=ERROR_UNMATCHED_CONDITION,
        no_village=ERROR_NO_VILLAGE,
    )
