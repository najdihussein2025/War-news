from __future__ import annotations

from typing import Any

from app.news.models import IncidentDetail
from app.news.services.incident_details.incident_detail_field_registry import (
    DID_GATES,
    GATE_DEPENDENTS,
    GATE_TO_DID,
    db_column,
)


def _admin_protected_columns(detail: IncidentDetail) -> set[str]:
    """DB columns an admin cleared: the gate itself plus its DID and dependents."""
    protected: set[str] = set()
    for gate in getattr(detail, "admin_cleared_gates", None) or []:
        api_fields = {gate, *GATE_DEPENDENTS.get(gate, ())}
        if gate in GATE_TO_DID:
            api_fields.add(GATE_TO_DID[gate])
        protected.update(db_column(field) for field in api_fields)
    return protected


def _gate_is_active(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value > 0
    return False


def _clear_orphaned_dids(detail: IncidentDetail) -> None:
    """Pipeline-side gate/DID rule: a DID needs its gate marked present."""
    for did_field, gate in DID_GATES.items():
        did_column = db_column(did_field)
        if getattr(detail, did_column, None) is None:
            continue
        if not _gate_is_active(getattr(detail, db_column(gate), None)):
            setattr(detail, did_column, None)


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
    protected = _admin_protected_columns(detail)
    for key, value in incoming.items():
        if not hasattr(IncidentDetail, key):
            continue
        if value is None:
            continue
        if key in protected:
            continue

        current = getattr(detail, key)
        column = IncidentDetail.__table__.columns.get(key)
        if column is not None and column.type.python_type is bool:
            setattr(detail, key, _merge_bool_flag(current, value))
        elif column is not None and column.type.python_type is int:
            setattr(detail, key, _merge_max_int(current, value))
        else:
            setattr(detail, key, _merge_prefer_non_null(current, value))
    _clear_orphaned_dids(detail)
