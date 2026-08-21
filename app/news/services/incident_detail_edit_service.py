from __future__ import annotations

from enum import Enum
from typing import Any

from app.core.text_sanitizer import strip_emoji_and_pictographs
from app.llm.dtos.extraction_dto import ExtractionCasualties
from app.news.models.incident import Incident
from app.news.models.incident_detail import DidValue, IncidentDetail
from app.news.services.category_mapper import compute_rollups
from app.news.services.incident_detail_field_registry import (
    AUTOMATED_API_FIELDS,
    DID_GATES,
    EDITABLE_API_FIELDS,
    GATE_DEPENDENTS,
    GATE_TO_DID,
    db_column,
)
from app.news.services.incident_detail_rollups import recompute_detail_rollups

ROLLUP_API_FIELDS: tuple[str, ...] = (
    "la_td",
    "la_ti",
    "un_td",
    "un_ti",
    "muni_td",
    "muni_ti",
    "car_d",
    "car_i",
    "total_con",
)


class IncidentDetailEditError(Exception):
    pass


def _gate_is_active_value(value: object) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    if isinstance(value, int):
        return value > 0
    if isinstance(value, str):
        return value.strip() != "" and value.strip() != "0"
    return False


def _serialize_api_value(value: object) -> int | str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value
    return str(value)


def _read_api_value(detail: IncidentDetail, api_field: str) -> int | str | None:
    return _serialize_api_value(getattr(detail, db_column(api_field), None))


def _coerce_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value not in (0, 1):
            raise IncidentDetailEditError("Flag fields must be 0 or 1.")
        return value == 1
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("", "0", "false", "no"):
            return False
        if normalized in ("1", "true", "yes"):
            return True
        raise IncidentDetailEditError("Flag fields must be 0 or 1.")
    raise IncidentDetailEditError("Flag fields must be 0 or 1.")


def _coerce_count(value: object, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise IncidentDetailEditError(f"{field_name} must be a non-negative integer.")
    if isinstance(value, int):
        if value < 0:
            raise IncidentDetailEditError(f"{field_name} must be a non-negative integer.")
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return None
        if not stripped.isdigit():
            raise IncidentDetailEditError(f"{field_name} must be a non-negative integer.")
        return int(stripped)
    raise IncidentDetailEditError(f"{field_name} must be a non-negative integer.")


def _coerce_did(value: object, field_name: str) -> DidValue | None:
    if value is None or value == "":
        return None
    if isinstance(value, DidValue):
        return value
    normalized = str(value).strip().upper()
    if normalized in ("D", "DIRECT"):
        return DidValue.D
    if normalized in ("ID", "INDIRECT"):
        return DidValue.ID
    raise IncidentDetailEditError(
        f"{field_name} must be D (direct) or ID (indirect) when set."
    )


def _coerce_text(value: object) -> str | None:
    if value is None:
        return None
    text = strip_emoji_and_pictographs(str(value)).strip()
    return text or None


_COUNT_DB_COLUMNS = frozenset(
    {
        "male_d",
        "male_i",
        "female_d",
        "female_i",
        "children_d",
        "children_i",
        "lam_d",
        "lam_i",
        "laf_d",
        "laf_i",
        "unm_d",
        "unm_i",
        "unf_d",
        "unf_i",
        "munim_d",
        "munim_i",
        "munif_d",
        "munif_i",
        "nbr_evap",
        "hosm_d",
        "hosm_i",
        "hosf_d",
        "hosf_i",
        "hcm_d",
        "hcm_i",
        "hcf_d",
        "hcf_i",
        "emer_d",
        "emer_i",
        "pressm_d",
        "pressm_i",
        "pressf_d",
        "pressf_i",
        "gbm_d",
        "gbm_i",
        "gbf_d",
        "gbf_i",
        "carm_d",
        "carm_i",
        "carf_d",
        "carf_i",
        "carc_d",
        "carc_i",
        "moto_d",
        "moto_i",
        "con_d",
        "con_i",
        "olives_trees_d",
        "other_d",
        "other_i",
        "car_nbr",
        "arrested",
    }
)


def _field_kind(api_field: str) -> str:
    if api_field in DID_GATES:
        return "did"
    db_col = db_column(api_field)
    if db_col in _COUNT_DB_COLUMNS:
        return "count"
    column = IncidentDetail.__table__.columns.get(db_col)
    if column is not None and column.type.python_type is bool:
        return "flag"
    return "text"


def _coerce_field(api_field: str, value: object) -> object:
    kind = _field_kind(api_field)
    if kind == "did":
        return _coerce_did(value, api_field)
    if kind == "count":
        return _coerce_count(value, api_field)
    if kind == "flag":
        return _coerce_bool(value)
    return _coerce_text(value)


def _validate_gate_and_did_rules(
    merged_api_values: dict[str, object],
    incoming: dict[str, object],
) -> None:
    for api_field, gate in DID_GATES.items():
        if api_field not in incoming:
            continue
        gate_value = merged_api_values.get(gate)
        if not _gate_is_active_value(gate_value):
            raise IncidentDetailEditError(
                f"{api_field} cannot be set when {gate} is not marked present."
            )

    for gate, dependents in GATE_DEPENDENTS.items():
        if gate not in incoming:
            continue
        if _gate_is_active_value(incoming[gate]):
            continue
        orphaned = [
            field
            for field in dependents
            if field in incoming and _has_meaningful_value(incoming[field])
        ]
        if orphaned:
            raise IncidentDetailEditError(
                f"When {gate} is cleared, dependent fields must also be cleared "
                f"(found values for: {', '.join(orphaned)})."
            )


def _validate_required_did(merged_api_values: dict[str, object]) -> None:
    for gate, did_field in GATE_TO_DID.items():
        if not _gate_is_active_value(merged_api_values.get(gate)):
            continue
        did_value = merged_api_values.get(did_field)
        if did_value is None or str(did_value).strip() == "":
            raise IncidentDetailEditError(
                f"{did_field} is required when {gate} is marked present "
                f"(must be D or ID)."
            )


def _has_meaningful_value(value: object) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value > 0
    if isinstance(value, str):
        return value.strip() != "" and value.strip() != "0"
    return True


def _detail_as_rollup_map(detail: IncidentDetail) -> dict[str, Any]:
    return {
        "la_td": detail.la_td,
        "la_ti": detail.la_ti,
        "un_td": detail.un_td,
        "un_ti": detail.un_ti,
        "muni_td": detail.muni_td,
        "muni_ti": detail.muni_ti,
        "hosd": detail.hosd,
        "hosi": detail.hosi,
        "hcd": detail.hcd,
        "hci": detail.hci,
        "pressd": detail.pressd,
        "pressi": detail.pressi,
        "gbd": detail.gbd,
        "gbi": detail.gbi,
        "card": detail.card,
        "cari": detail.cari,
        "emer_d": detail.emer_d,
        "emer_i": detail.emer_i,
    }


def _build_diff(
    before: dict[str, int | str | None],
    after: dict[str, int | str | None],
) -> tuple[dict[str, int | str | None], dict[str, int | str | None]]:
    old_values: dict[str, int | str | None] = {}
    new_values: dict[str, int | str | None] = {}
    for key in before:
        if before[key] != after.get(key):
            old_values[key] = before[key]
            new_values[key] = after.get(key)
    return old_values, new_values


def apply_incident_detail_edits(
    incident: Incident,
    detail: IncidentDetail,
    incoming: dict[str, Any],
) -> tuple[dict[str, int | str | None], dict[str, int | str | None]]:
    """Validate and apply partial incident_details edits.

    Returns (old_values, new_values) diffs keyed by API field names.
    """
    if not incoming:
        raise IncidentDetailEditError("At least one field must be provided.")

    automated = sorted(set(incoming) & AUTOMATED_API_FIELDS)
    if automated:
        raise IncidentDetailEditError(
            f"Automated fields cannot be edited directly: {', '.join(automated)}."
        )

    unknown = sorted(set(incoming) - EDITABLE_API_FIELDS)
    if unknown:
        raise IncidentDetailEditError(
            f"Unknown or non-editable fields: {', '.join(unknown)}."
        )

    coerced_incoming: dict[str, object] = {}
    for api_field, raw_value in incoming.items():
        coerced_incoming[api_field] = _coerce_field(api_field, raw_value)

    merged_api_values: dict[str, object] = {}
    for api_field in EDITABLE_API_FIELDS:
        if api_field in coerced_incoming:
            merged_api_values[api_field] = coerced_incoming[api_field]
        else:
            merged_api_values[api_field] = _read_api_value(detail, api_field)

    _validate_gate_and_did_rules(merged_api_values, coerced_incoming)
    _validate_required_did(merged_api_values)

    tracked_fields = set(coerced_incoming) | set(ROLLUP_API_FIELDS)
    before_snapshot = {
        api_field: _read_api_value(detail, api_field) for api_field in tracked_fields
    }
    before_totals = (incident.total_deaths, incident.total_injuries)

    for api_field, value in coerced_incoming.items():
        setattr(detail, db_column(api_field), value)

    recompute_detail_rollups(detail)

    root_casualties = ExtractionCasualties(
        deaths=incident.deaths,
        injuries=incident.injuries,
    )
    incident.total_deaths, incident.total_injuries = compute_rollups(
        _detail_as_rollup_map(detail),
        root_casualties,
    )

    after_snapshot = {
        api_field: _read_api_value(detail, api_field) for api_field in tracked_fields
    }
    old_values, new_values = _build_diff(before_snapshot, after_snapshot)

    if before_totals != (incident.total_deaths, incident.total_injuries):
        old_values["total_deaths"] = before_totals[0]
        new_values["total_deaths"] = incident.total_deaths
        old_values["total_injuries"] = before_totals[1]
        new_values["total_injuries"] = incident.total_injuries

    return old_values, new_values
