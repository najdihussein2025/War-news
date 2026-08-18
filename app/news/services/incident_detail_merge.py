from __future__ import annotations

from typing import Any

from app.news.models import IncidentDetail


def _merge_max_int(current: int | None, incoming: Any) -> int | None:
    incoming_value = incoming if isinstance(incoming, int) else None
    if current is None and incoming_value is None:
        return None
    return max(current or 0, incoming_value or 0)


def _merge_prefer_non_null(current: Any, incoming: Any) -> Any:
    if current is not None:
        return current
    return incoming


def _merge_bool_flag(current: bool | None, incoming: Any) -> bool | None:
    if current is True or incoming is True:
        return True
    if current is False or incoming is False:
        return False
    return None


def merge_incident_detail_fields(
    detail: IncidentDetail,
    incoming: dict[str, Any],
) -> None:
    """Merge mapped category/detail fields into an existing IncidentDetail row."""
    for key, value in incoming.items():
        if not hasattr(IncidentDetail, key):
            continue
        if value is None:
            continue

        current = getattr(detail, key)
        column = IncidentDetail.__table__.columns.get(key)
        if column is not None and column.type.python_type is bool:
            setattr(detail, key, _merge_bool_flag(current, value))
        elif column is not None and column.type.python_type is int:
            setattr(detail, key, _merge_max_int(current, value))
        else:
            setattr(detail, key, _merge_prefer_non_null(current, value))
