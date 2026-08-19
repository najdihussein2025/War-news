from __future__ import annotations

from typing import Any

from app.news.models.incident_detail import IncidentDetail
from app.news.services.incident_detail_field_registry import (
    CATEGORY_SECTIONS,
    DID_GATES,
    db_column,
)

CategorySectionPayload = dict[str, int | str | bool | None]


def _gate_is_active(detail: IncidentDetail, gate_column: str) -> bool:
    value = getattr(detail, gate_column, None)
    if value is True:
        return True
    if isinstance(value, int):
        return value > 0
    if isinstance(value, str):
        return value.strip() != ""
    return False


def _section_is_active(detail: IncidentDetail, gate_columns: tuple[str, ...]) -> bool:
    return any(_gate_is_active(detail, gate) for gate in gate_columns)


def _serialize_value(value: object) -> int | str | bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value
    return str(value)


def _serialize_field(
    detail: IncidentDetail,
    api_field: str,
) -> int | str | bool | None:
    db_col = db_column(api_field)
    gate_column = DID_GATES.get(api_field)
    if gate_column is not None and not _gate_is_active(detail, gate_column):
        return None
    return _serialize_value(getattr(detail, db_col, None))


def serialize_category_section(
    detail: IncidentDetail | None,
    section_key: str,
) -> CategorySectionPayload | None:
    if detail is None:
        return None

    section = CATEGORY_SECTIONS[section_key]
    if not _section_is_active(detail, section["gates"]):
        return None

    payload: CategorySectionPayload = {}
    for api_field in section["fields"]:
        value = _serialize_field(detail, api_field)
        if value is not None:
            payload[api_field] = value
    return payload or None


def serialize_incident_category_sections(
    detail: IncidentDetail | None,
) -> dict[str, CategorySectionPayload | None]:
    return {
        section_key: serialize_category_section(detail, section_key)
        for section_key in CATEGORY_SECTIONS
    }
