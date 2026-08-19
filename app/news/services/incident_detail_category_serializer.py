from __future__ import annotations

from typing import Any

from app.news.models.incident_detail import IncidentDetail

# Flat API field name -> IncidentDetail column name when they differ.
_API_TO_DB_COLUMN: dict[str, str] = {
    "child_d": "children_d",
    "child_i": "children_i",
    "hc_m_d": "hcm_d",
    "hc_m_i": "hcm_i",
    "hc_f_d": "hcf_d",
    "hc_f_i": "hcf_i",
    "press_m_d": "pressm_d",
    "press_m_i": "pressm_i",
    "press_f_d": "pressf_d",
    "press_f_i": "pressf_i",
    "muni_m_d": "munim_d",
    "muni_m_i": "munim_i",
    "muni_f_d": "munif_d",
    "muni_f_i": "munif_i",
    "gb_m_d": "gbm_d",
    "gb_m_i": "gbm_i",
    "gb_f_d": "gbf_d",
    "gb_f_i": "gbf_i",
    "car_d": "card",
    "car_i": "cari",
    "car_m_d": "carm_d",
    "car_m_i": "carm_i",
    "car_f_d": "carf_d",
    "car_f_i": "carf_i",
    "car_c_d": "carc_d",
    "car_c_i": "carc_i",
    "hos_m_d": "hosm_d",
    "hos_m_i": "hosm_i",
    "hos_f_d": "hosf_d",
    "hos_f_i": "hosf_i",
    "sch_damage_level": "school_damage_level",
}

# DID fields paired with their controlling gate column.
_DID_GATES: dict[str, str] = {
    "la_did": "la",
    "un_did": "unifil",
    "muni_did": "muni",
    "sch_did": "school",
    "uni_did": "uni",
    "chu_did": "church",
    "mos_did": "mosque",
    "ceme_did": "ceme",
    "releg_did": "releg",
    "arch_did": "archeo",
    "hos_did": "hosp",
    "hc_did": "hc",
    "press_did": "press",
    "gb_did": "gov",
    "road_d_id": "road",
    "moto_did": "moto",
    "water_did": "water",
    "electric_did": "electric",
    "mj_did": "mjnoub",
    "other_did": "other",
}

CategorySectionPayload = dict[str, int | str | bool | None]

_CATEGORY_SECTIONS: dict[str, dict[str, Any]] = {
    "lebanese_army": {
        "gates": ("la",),
        "fields": (
            "la",
            "la_did",
            "la_bldg",
            "la_v",
            "lam_d",
            "lam_i",
            "laf_d",
            "laf_i",
            "la_td",
            "la_ti",
        ),
    },
    "unifil": {
        "gates": ("unifil",),
        "fields": (
            "unifil",
            "un_did",
            "un_bldg",
            "un_v",
            "unm_d",
            "unm_i",
            "unf_d",
            "unf_i",
            "un_td",
            "un_ti",
        ),
    },
    "municipality": {
        "gates": ("muni",),
        "fields": (
            "muni",
            "muni_did",
            "muni_bldg",
            "muni_empl",
            "muni_m_d",
            "muni_m_i",
            "muni_f_d",
            "muni_f_i",
            "muni_td",
            "muni_ti",
        ),
    },
    "school_university": {
        "gates": ("school", "uni"),
        "fields": (
            "school",
            "sch_did",
            "school_name",
            "sch_damage_level",
            "uni",
            "uni_did",
            "uni_name",
        ),
    },
    "religious_cultural": {
        "gates": ("church", "mosque", "ceme", "releg", "archeo"),
        "fields": (
            "church",
            "chu_did",
            "chu_n",
            "mosque",
            "mos_did",
            "mosque_n",
            "ceme",
            "ceme_did",
            "ceme_n",
            "releg",
            "releg_did",
            "releg_n",
            "archeo",
            "arch_did",
            "arch_n",
        ),
    },
    "hospital": {
        "gates": ("hosp",),
        "fields": (
            "hosp",
            "hos_did",
            "hos_status",
            "hos_n",
            "hos_damage_level",
            "nbr_evap",
            "hos_m_d",
            "hos_m_i",
            "hos_f_d",
            "hos_f_i",
        ),
    },
    "health_center": {
        "gates": ("hc",),
        "fields": (
            "hc",
            "hc_rela",
            "hc_did",
            "hc_damage_level",
            "hc_m_d",
            "hc_m_i",
            "hc_f_d",
            "hc_f_i",
        ),
    },
    "emergency_civil_defense": {
        "gates": ("emer",),
        "fields": (
            "emer",
            "e_cars",
            "car_nbr",
            "emer_rela",
            "emer_d",
            "emer_i",
        ),
    },
    "press": {
        "gates": ("press",),
        "fields": (
            "press",
            "channel",
            "press_did",
            "press_m_d",
            "press_m_i",
            "press_f_d",
            "press_f_i",
        ),
    },
    "government_building": {
        "gates": ("gov",),
        "fields": (
            "gov",
            "gov_bui",
            "gov_n",
            "gb_did",
            "gb_m_d",
            "gb_m_i",
            "gb_f_d",
            "gb_f_i",
        ),
    },
    "road_bridge": {
        "gates": ("road", "bridge"),
        "fields": (
            "road",
            "road_d_id",
            "road_blocked",
            "road_name",
            "bridge",
            "bridge_blocked",
            "bridge_name",
        ),
    },
    "vehicles": {
        "gates": ("car", "moto", "con_veh"),
        "fields": (
            "car",
            "car_d",
            "car_i",
            "car_m_d",
            "car_m_i",
            "car_f_d",
            "car_f_i",
            "car_c_d",
            "car_c_i",
            "moto",
            "moto_did",
            "moto_d",
            "moto_i",
            "con_veh",
            "con_d",
            "con_i",
            "excavator",
            "bulldozer",
            "camion",
            "bobcat",
            "tracteur",
            "total_con",
        ),
    },
    "crossings_other": {
        "gates": (
            "crossing",
            "litani",
            "zahrani",
            "drone_f",
            "water",
            "electric",
            "mjnoub",
            "other",
        ),
        "fields": (
            "crossing",
            "litani",
            "zahrani",
            "drone_f",
            "water",
            "water_did",
            "water_type",
            "electric",
            "electric_did",
            "electric_type",
            "olives_trees_d",
            "mjnoub",
            "mj_did",
            "other",
            "other_did",
            "other_type",
            "other_d",
            "other_i",
        ),
    },
    "warning_classification": {
        "gates": ("no_warning", "warning", "genocide", "building", "apart"),
        "fields": (
            "no_warning",
            "warning",
            "genocide",
            "building",
            "apart",
        ),
    },
}


def _db_column(api_field: str) -> str:
    return _API_TO_DB_COLUMN.get(api_field, api_field)


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
    db_column = _db_column(api_field)
    gate_column = _DID_GATES.get(api_field)
    if gate_column is not None and not _gate_is_active(detail, gate_column):
        return None
    return _serialize_value(getattr(detail, db_column, None))


def serialize_category_section(
    detail: IncidentDetail | None,
    section_key: str,
) -> CategorySectionPayload | None:
    if detail is None:
        return None

    section = _CATEGORY_SECTIONS[section_key]
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
        for section_key in _CATEGORY_SECTIONS
    }
