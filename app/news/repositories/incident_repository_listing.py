"""Cursor, ordering, and filter policy for the incident queue.

The repository keeps verification-flag predicates because they are also used by
mutation workflows. This mixin owns the read-side query policy instead.
"""

import base64
import json
from datetime import date, datetime, time
from typing import Any
from uuid import UUID

from sqlalchemy import and_, false, func, or_

from app.news.constants.air_violation_conditions import AIR_VIOLATION_CONDITION_ID_TUPLE
from app.news.dtos import IncidentListParams
from app.news.models import (
    Condition,
    Incident,
    IncidentOrigin,
    MessageStatus,
    RawMessage,
    Village,
)
from app.news.models.summary_bulletin import SummaryBulletin
from app.sources.models import Source


class IncidentRepositoryListQueryMixin:
    @classmethod
    def _list_filters(
        cls,
        params: IncidentListParams,
        *,
        event_date_expr=None,
    ) -> list[object]:
        event_date_column = event_date_expr if event_date_expr is not None else Incident.event_date
        filters: list[object] = [
            Incident.is_deleted.is_(False),
            Incident.village_id.is_not(None),
            Incident.condition_id.not_in(AIR_VIOLATION_CONDITION_ID_TUPLE),
            cls._visible_incident_scope_filter(),
            # Summary-created incidents have no raw message of their own (so no stage can
            # re-read the bulletin for them); every other incident must be materialized.
            or_(
                Incident.origin == IncidentOrigin.summary,
                and_(
                    RawMessage.id.is_not(None),
                    RawMessage.status == MessageStatus.materialized,
                    ~RawMessage.raw_payload.op("?")("ocr_text"),
                ),
            ),
        ]
        if params.verification_status is None:
            filters.append(Incident.verification_status != "rejected")
        if params.village:
            village_pattern = f"%{params.village}%"
            filters.append(
                or_(
                    Village.ref_name_en.ilike(village_pattern),
                    Village.cad_name.ilike(village_pattern),
                    Village.ref_name_ar.ilike(village_pattern),
                )
            )
        if params.condition:
            filters.append(
                or_(
                    Condition.action_en.ilike(f"%{params.condition}%"),
                    Condition.action_ar.ilike(f"%{params.condition}%"),
                )
            )
        if params.source_type:
            filters.append(Source.type == params.source_type.lower())
        if params.source_name:
            filters.append(func.coalesce(RawMessage.source_name, SummaryBulletin.channel) == params.source_name)
        if params.event_date_from is not None:
            filters.append(event_date_column >= params.event_date_from)
        if params.event_date_to is not None:
            filters.append(event_date_column <= params.event_date_to)
        if params.flagged_only:
            filters.append(
                or_(
                    Incident.duplicate_flag.is_(True),
                    cls._needs_verification_column(),
                )
            )
        if params.verification_status == "needs_verification":
            filters.append(cls._needs_verification_column())
        elif params.verification_status == "matched":
            # Legacy alias: "confident / not needing verification".
            filters.append(Incident.verification_status != "needs_verification")
        elif params.verification_status is not None:
            filters.append(Incident.verification_status == params.verification_status)
            if params.verification_status in ("auto_processed", "verified"):
                filters.append(~cls._needs_verification_column())
        if params.verification_type == "duplicate":
            filters.append(Incident.duplicate_flag.is_(True))
        elif params.verification_type == "casualty_missing_number":
            filters.append(cls._visible_flag_exists("count_missing"))
        elif params.verification_type == "casualty_aggregate_toll":
            filters.append(cls._visible_flag_exists("aggregate_no_breakdown"))
        if params.duplicate_only:
            filters.append(Incident.duplicate_flag.is_(True))
        if params.has_casualties:
            filters.append(
                or_(
                    func.coalesce(Incident.total_deaths, 0) > 0,
                    func.coalesce(Incident.total_injuries, 0) > 0,
                )
            )
        if params.summary_added:
            filters.append(Incident.origin == IncidentOrigin.summary)
        if params.decision_reason:
            filters.append(Incident.decision_reason == params.decision_reason)
        return filters

    @classmethod
    def _outside_range_needs_verification_filters(
        cls, params: IncidentListParams
    ) -> list[object] | None:
        """Needs-verification rows hidden only by the event date range."""
        if params.verification_status != "needs_verification" and params.verification_type is None:
            return None
        if params.event_date_from is None and params.event_date_to is None:
            return None
        undated = params.model_copy(update={"event_date_from": None, "event_date_to": None})
        outside = [Incident.event_date.is_(None)]
        if params.event_date_from is not None:
            outside.append(Incident.event_date < params.event_date_from)
        if params.event_date_to is not None:
            outside.append(Incident.event_date > params.event_date_to)
        return [*cls._list_filters(undated), cls._needs_verification_column(), or_(*outside)]

    @staticmethod
    def _list_ordering(params: IncidentListParams) -> tuple[object, ...]:
        event_datetime = func.coalesce(
            RawMessage.message_datetime,
            RawMessage.received_at,
        )
        event_date = func.coalesce(
            Incident.event_date,
            func.date(event_datetime),
        )
        created_at = func.coalesce(Incident.created_at, RawMessage.received_at)
        raw_message_sort_id = func.coalesce(RawMessage.id, 0)
        if params.sort_order == "oldest":
            return (
                event_date.asc(),
                Incident.event_time.asc().nullslast(),
                created_at.asc(),
                raw_message_sort_id.asc(),
                Incident.id.asc().nullslast(),
            )
        return (
            event_date.desc(),
            Incident.event_time.desc().nullslast(),
            created_at.desc(),
            raw_message_sort_id.desc(),
            Incident.id.desc().nullslast(),
        )

    @staticmethod
    def _decode_list_cursor(cursor: str | None) -> dict[str, object] | None:
        if cursor is None:
            return None
        try:
            payload = json.loads(
                base64.urlsafe_b64decode(cursor.encode("ascii") + b"===")
            )
            created_at = datetime.fromisoformat(payload["sort_created_at"])
            event_date = date.fromisoformat(payload["sort_event_date"])
            event_time_is_null = payload["sort_event_time_is_null"]
            event_time = (
                None
                if event_time_is_null
                else time.fromisoformat(payload["sort_event_time"])
            )
            incident_id = payload["incident_id"]
            raw_message_id = payload["raw_message_id"]
            return {
                "sort_created_at": created_at,
                "sort_event_date": event_date,
                "sort_event_time_is_null": event_time_is_null,
                "sort_event_time": event_time,
                "raw_message_id": (
                    int(raw_message_id) if raw_message_id is not None else None
                ),
                "incident_id": UUID(incident_id) if incident_id is not None else None,
            }
        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise ValueError("Invalid incidents cursor.") from exc

    @staticmethod
    def _encode_list_cursor(row: Any) -> str:
        event_time = row["event_time"]
        payload = {
            "sort_created_at": row["created_at"].isoformat(),
            "sort_event_date": row["event_date"].isoformat(),
            "sort_event_time_is_null": event_time is None,
            "sort_event_time": event_time.isoformat()
            if event_time is not None
            else None,
            "raw_message_id": row["raw_message_id"],
            "incident_id": str(row["id"]) if row["id"] is not None else None,
        }
        return (
            base64.urlsafe_b64encode(
                json.dumps(payload, separators=(",", ":")).encode("utf-8")
            )
            .decode("ascii")
            .rstrip("=")
        )

    @staticmethod
    def _list_cursor_filter(
        params: IncidentListParams,
        cursor: dict[str, object],
        created_at: object,
        event_date: object,
    ) -> object:
        created_value = cursor["sort_created_at"]
        event_date_value = cursor["sort_event_date"]
        event_time_value = cursor["sort_event_time"]
        raw_message_id = cursor["raw_message_id"]
        raw_message_sort_id = func.coalesce(RawMessage.id, 0)
        raw_message_sort_value = raw_message_id if raw_message_id is not None else 0
        incident_id = cursor["incident_id"]
        before = params.sort_order == "newest"
        comparison = (
            (lambda column, value: column < value)
            if before
            else (lambda column, value: column > value)
        )
        created_equal = created_at == created_value
        event_date_equal = event_date == event_date_value
        event_time_equal = (
            Incident.event_time.is_(None)
            if event_time_value is None
            else Incident.event_time == event_time_value
        )
        event_time_after = (
            Incident.event_time.is_(None) if event_time_value is not None else false()
        )
        if event_time_value is not None:
            event_time_after = or_(
                comparison(Incident.event_time, event_time_value),
                Incident.event_time.is_(None),
            )
        incident_after = (
            or_(Incident.id.is_(None), comparison(Incident.id, incident_id))
            if incident_id is not None
            else false()
        )
        return or_(
            comparison(event_date, event_date_value),
            and_(event_date_equal, event_time_after),
            and_(
                event_date_equal,
                event_time_equal,
                comparison(created_at, created_value),
            ),
            and_(
                event_date_equal,
                event_time_equal,
                created_equal,
                comparison(raw_message_sort_id, raw_message_sort_value),
            ),
            and_(
                event_date_equal,
                event_time_equal,
                created_equal,
                raw_message_sort_id == raw_message_sort_value,
                incident_after,
            ),
        )

    @staticmethod
    def _has_incident_scoped_filters(params: IncidentListParams) -> bool:
        return bool(
            params.village
            or params.condition
            or params.source_type
            or params.source_name
            or params.event_date_from is not None
            or params.event_date_to is not None
            or params.flagged_only
            or params.verification_status is not None
            or params.duplicate_only
            or params.summary_added
            or params.decision_reason
        )


