from __future__ import annotations

from typing import Any

# Flat API field name -> IncidentDetail column name when they differ.
API_TO_DB_COLUMN: dict[str, str] = {
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

DB_TO_API_COLUMN: dict[str, str] = {
    db: api for api, db in API_TO_DB_COLUMN.items()
}

# DID fields paired with their controlling gate column.
DID_GATES: dict[str, str] = {
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

GATE_TO_DID: dict[str, str] = {gate: did for did, gate in DID_GATES.items()}

# Rollup / computed columns — not directly settable via manual edit.
AUTOMATED_API_FIELDS: frozenset[str] = frozenset(
    {
        "la_td",
        "la_ti",
        "un_td",
        "un_ti",
        "muni_td",
        "muni_ti",
        "car_d",
        "car_i",
        "total_con",
    }
)

AUTOMATED_DB_COLUMNS: frozenset[str] = frozenset(
    {
        "la_td",
        "la_ti",
        "un_td",
        "un_ti",
        "muni_td",
        "muni_ti",
        "hosd",
        "hosi",
        "hcd",
        "hci",
        "pressd",
        "pressi",
        "gbd",
        "gbi",
        "card",
        "cari",
        "total_con",
    }
)

CASUALTY_DEMOGRAPHICS_API_FIELDS: tuple[str, ...] = (
    "male_d",
    "male_i",
    "female_d",
    "female_i",
    "child_d",
    "child_i",
    "obs_duties",
    "isf_gs",
    "fire",
    "arrested",
    "lib_y_n",
)

CATEGORY_SECTIONS: dict[str, dict[str, Any]] = {
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


def db_column(api_field: str) -> str:
    return API_TO_DB_COLUMN.get(api_field, api_field)


def api_column(db_field: str) -> str:
    return DB_TO_API_COLUMN.get(db_field, db_field)


def build_gate_dependents() -> dict[str, frozenset[str]]:
    """Map each gate flag to API field names cleared when the gate is turned off."""
    dependents: dict[str, set[str]] = {}

    for section in CATEGORY_SECTIONS.values():
        gate_names = frozenset(section["gates"])
        current_gate: str | None = None
        for api_field in section["fields"]:
            if api_field in gate_names:
                current_gate = api_field
                dependents.setdefault(current_gate, set())
                continue
            if current_gate is not None:
                dependents.setdefault(current_gate, set()).add(api_field)

    return {gate: frozenset(fields) for gate, fields in dependents.items()}


GATE_DEPENDENTS: dict[str, frozenset[str]] = build_gate_dependents()

EDITABLE_API_FIELDS: frozenset[str] = frozenset(
    field
    for section in CATEGORY_SECTIONS.values()
    for field in section["fields"]
    if field not in AUTOMATED_API_FIELDS
) | frozenset(CASUALTY_DEMOGRAPHICS_API_FIELDS)
