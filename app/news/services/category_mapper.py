from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.llm.dtos.extraction_dto import (
    ExtractionCasualties,
    ExtractionCategory,
    ExtractionCategoryKey,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword sets for name-based classification
# ---------------------------------------------------------------------------

_SCHOOL_KEYWORDS: frozenset[str] = frozenset(
    {"مدرسة", "school", "ثانوية", "ابتدائية", "رياض"}
)
_UNI_KEYWORDS: frozenset[str] = frozenset(
    {"جامعة", "university", "معهد", "كلية", "college"}
)
_CHURCH_KEYWORDS: frozenset[str] = frozenset(
    {"كنيسة", "church", "chapel", "كاتدرائية"}
)
_MOSQUE_KEYWORDS: frozenset[str] = frozenset({"مسجد", "mosque", "جامع"})
_CEME_KEYWORDS: frozenset[str] = frozenset({"مقبرة", "cemetery", "مدفن"})
_ARCHEO_KEYWORDS: frozenset[str] = frozenset(
    {"أثري", "archeolog", "تراث", "heritage"}
)
_RELEG_KEYWORDS: frozenset[str] = frozenset({"ديني", "religious", "مزار", "shrine"})
_BRIDGE_KEYWORDS: frozenset[str] = frozenset({"جسر", "bridge"})
_ROAD_KEYWORDS: frozenset[str] = frozenset({"طريق", "road", "أوتوستراد", "autostrada"})
_BLOCKED_KEYWORDS: frozenset[str] = frozenset(
    {"قطع", "blocked", "تعذر", "مسدود", "blockage"}
)
_LITANI_KEYWORDS: frozenset[str] = frozenset({"litani", "ليتاني", "الليتاني"})
_ZAHRANI_KEYWORDS: frozenset[str] = frozenset({"zahrani", "زرقاني", "الزرقاني"})
_DRONE_KEYWORDS: frozenset[str] = frozenset({"drone", "محلقة", "مسيرة", "طائرة مسيرة"})
_WATER_KEYWORDS: frozenset[str] = frozenset({"water", "مياه", "آبار", "بئر", "سقاية"})
_ELECTRIC_KEYWORDS: frozenset[str] = frozenset({"electric", "كهرب", "محطة كهرب"})
_OLIVE_KEYWORDS: frozenset[str] = frozenset({"olive", "زيتون", "أشجار"})
_MJNOUB_KEYWORDS: frozenset[str] = frozenset({"mjnoub", "مجنوب"})

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _contains_any(text: str, keywords: frozenset[str]) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def _did_str(category: ExtractionCategory) -> str | None:
    return category.did.value if category.did is not None else None


def _safe_add(*values: int | None) -> int | None:
    """Sum non-None values; return None when every value is None."""
    non_null = [v for v in values if v is not None]
    return sum(non_null) if non_null else None


# ---------------------------------------------------------------------------
# Per-category handler functions
# ---------------------------------------------------------------------------


def _map_lebanese_army(cat: ExtractionCategory, out: dict[str, Any]) -> None:
    out["la"] = True
    out["la_did"] = _did_str(cat)
    c = cat.casualties
    if c is not None:
        out["lam_d"] = c.male_deaths
        out["lam_i"] = c.male_injuries
        out["laf_d"] = c.female_deaths
        out["laf_i"] = c.female_injuries
        out["la_td"] = _safe_add(c.male_deaths, c.female_deaths)
        out["la_ti"] = _safe_add(c.male_injuries, c.female_injuries)


def _map_unifil(cat: ExtractionCategory, out: dict[str, Any]) -> None:
    out["unifil"] = True
    out["un_did"] = _did_str(cat)
    c = cat.casualties
    if c is not None:
        out["unm_d"] = c.male_deaths
        out["unm_i"] = c.male_injuries
        out["unf_d"] = c.female_deaths
        out["unf_i"] = c.female_injuries
        out["un_td"] = _safe_add(c.male_deaths, c.female_deaths)
        out["un_ti"] = _safe_add(c.male_injuries, c.female_injuries)


def _map_municipality(cat: ExtractionCategory, out: dict[str, Any]) -> None:
    out["muni"] = True
    out["muni_did"] = _did_str(cat)
    c = cat.casualties
    if c is not None:
        out["munim_d"] = c.male_deaths
        out["munim_i"] = c.male_injuries
        out["munif_d"] = c.female_deaths
        out["munif_i"] = c.female_injuries
        out["muni_td"] = _safe_add(c.male_deaths, c.female_deaths)
        out["muni_ti"] = _safe_add(c.male_injuries, c.female_injuries)


def _map_hospital(cat: ExtractionCategory, out: dict[str, Any]) -> None:
    out["hosp"] = True
    out["hos_did"] = _did_str(cat)
    out["hos_n"] = cat.name
    c = cat.casualties
    if c is not None:
        out["hosm_d"] = c.male_deaths
        out["hosm_i"] = c.male_injuries
        out["hosf_d"] = c.female_deaths
        out["hosf_i"] = c.female_injuries
        out["hosd"] = _safe_add(c.male_deaths, c.female_deaths)
        out["hosi"] = _safe_add(c.male_injuries, c.female_injuries)


def _map_health_center(cat: ExtractionCategory, out: dict[str, Any]) -> None:
    out["hc"] = True
    out["hc_did"] = _did_str(cat)
    c = cat.casualties
    if c is not None:
        out["hcm_d"] = c.male_deaths
        out["hcm_i"] = c.male_injuries
        out["hcf_d"] = c.female_deaths
        out["hcf_i"] = c.female_injuries
        out["hcd"] = _safe_add(c.male_deaths, c.female_deaths)
        out["hci"] = _safe_add(c.male_injuries, c.female_injuries)


def _map_press(cat: ExtractionCategory, out: dict[str, Any]) -> None:
    out["press"] = True
    out["press_did"] = _did_str(cat)
    out["channel"] = cat.name
    c = cat.casualties
    if c is not None:
        out["pressm_d"] = c.male_deaths
        out["pressm_i"] = c.male_injuries
        out["pressf_d"] = c.female_deaths
        out["pressf_i"] = c.female_injuries
        out["pressd"] = _safe_add(c.male_deaths, c.female_deaths)
        out["pressi"] = _safe_add(c.male_injuries, c.female_injuries)


def _map_government_building(cat: ExtractionCategory, out: dict[str, Any]) -> None:
    out["gov"] = True
    out["gb_did"] = _did_str(cat)
    out["gov_n"] = cat.name
    c = cat.casualties
    if c is not None:
        out["gbm_d"] = c.male_deaths
        out["gbm_i"] = c.male_injuries
        out["gbf_d"] = c.female_deaths
        out["gbf_i"] = c.female_injuries
        out["gbd"] = _safe_add(c.male_deaths, c.female_deaths)
        out["gbi"] = _safe_add(c.male_injuries, c.female_injuries)


def _map_vehicles(cat: ExtractionCategory, out: dict[str, Any]) -> None:
    v = cat.vehicles
    if v is None:
        out["car"] = True
        _map_car_casualties(cat, out)
        return

    if v.car:
        out["car"] = True
        _map_car_casualties(cat, out)

    if v.moto:
        out["moto"] = True
        out["moto_did"] = _did_str(cat)
        if v.moto_d is not None:
            out["moto_d"] = v.moto_d
        if v.moto_i is not None:
            out["moto_i"] = v.moto_i

    construction_flags = (
        v.excavator,
        v.bulldozer,
        v.camion,
        v.bobcat,
        v.tracteur,
    )
    if v.con_veh or any(construction_flags):
        out["con_veh"] = True
        if v.excavator:
            out["excavator"] = True
        if v.bulldozer:
            out["bulldozer"] = True
        if v.camion:
            out["camion"] = True
        if v.bobcat:
            out["bobcat"] = True
        if v.tracteur:
            out["tracteur"] = True
        if v.con_d is not None:
            out["con_d"] = v.con_d
        if v.con_i is not None:
            out["con_i"] = v.con_i
        total_con = sum(
            1
            for flag in construction_flags
            if flag
        )
        if total_con:
            out["total_con"] = total_con


def _map_car_casualties(cat: ExtractionCategory, out: dict[str, Any]) -> None:
    c = cat.casualties
    if c is None:
        return
    out["carm_d"] = c.male_deaths
    out["carm_i"] = c.male_injuries
    out["carf_d"] = c.female_deaths
    out["carf_i"] = c.female_injuries
    out["carc_d"] = c.children_deaths
    out["carc_i"] = c.children_injuries
    out["card"] = _safe_add(c.male_deaths, c.female_deaths)
    out["cari"] = _safe_add(c.male_injuries, c.female_injuries)


def _map_emergency_civil_defense(cat: ExtractionCategory, out: dict[str, Any]) -> None:
    out["emer"] = True
    c = cat.casualties
    if c is not None:
        out["emer_d"] = c.deaths
        out["emer_i"] = c.injuries


def _map_crossings_other(cat: ExtractionCategory, out: dict[str, Any]) -> None:
    name = cat.name or ""
    combined = name.lower()
    did = _did_str(cat)

    if _contains_any(combined, _LITANI_KEYWORDS):
        out["litani"] = True
    elif _contains_any(combined, _ZAHRANI_KEYWORDS):
        out["zahrani"] = True
    elif _contains_any(combined, _DRONE_KEYWORDS):
        out["drone_f"] = True
    elif _contains_any(name, _WATER_KEYWORDS):
        out["water"] = True
        out["water_did"] = did
        if name.strip():
            out["water_type"] = cat.name
    elif _contains_any(name, _ELECTRIC_KEYWORDS):
        out["electric"] = True
        out["electric_did"] = did
        if name.strip():
            out["electric_type"] = cat.name
    elif _contains_any(combined, _MJNOUB_KEYWORDS):
        out["mjnoub"] = True
        out["mj_did"] = did
    elif _contains_any(name, _OLIVE_KEYWORDS):
        if cat.casualties is not None and cat.casualties.deaths is not None:
            out["olives_trees_d"] = cat.casualties.deaths
        else:
            out["other"] = True
            out["other_did"] = did
            out["other_type"] = cat.name or "olives_trees"
    else:
        out["crossing"] = True
        out["other"] = True
        out["other_did"] = did
        if name.strip():
            out["other_type"] = cat.name

    c = cat.casualties
    if c is not None:
        if c.deaths is not None and "olives_trees_d" not in out:
            out["other_d"] = c.deaths
        if c.injuries is not None:
            out["other_i"] = c.injuries


def _map_road_bridge(cat: ExtractionCategory, out: dict[str, Any]) -> None:
    name = cat.name or ""
    did = _did_str(cat)
    is_bridge = _contains_any(name, _BRIDGE_KEYWORDS)
    is_road = _contains_any(name, _ROAD_KEYWORDS) or not is_bridge
    blocked = _contains_any(name, _BLOCKED_KEYWORDS)

    if is_bridge:
        out["bridge"] = True
        if name.strip():
            out["bridge_name"] = cat.name
        if blocked:
            out["bridge_blocked"] = True
    if is_road:
        out["road"] = True
        out["road_d_id"] = did
        if name.strip():
            out["road_name"] = cat.name
        if blocked:
            out["road_blocked"] = True


def _map_warning_classification(cat: ExtractionCategory, out: dict[str, Any]) -> None:
    name = (cat.name or "").lower()
    if "no_warning" in name or "لا تحذير" in name:
        out["no_warning"] = True
    elif "warning" in name or "تحذير" in name:
        out["warning"] = True
    if "genocide" in name or "إبادة" in name:
        out["genocide"] = True
    if "building" in name or "مبن" in name or "مبان" in name:
        out["building"] = True
    if "apart" in name or "شقة" in name or "شقق" in name:
        out["apart"] = True


def _map_school_university(cat: ExtractionCategory, out: dict[str, Any]) -> None:
    name = cat.name or ""
    if _contains_any(name, _SCHOOL_KEYWORDS):
        out["school"] = True
        out["sch_did"] = _did_str(cat)
        out["school_name"] = cat.name
    elif _contains_any(name, _UNI_KEYWORDS):
        out["uni"] = True
        out["uni_did"] = _did_str(cat)
        out["uni_name"] = cat.name
    else:
        # other/other_type columns confirmed present in incident_detail.py
        out["other"] = True
        out["other_did"] = _did_str(cat)
        out["other_type"] = "school_university_unclassified"
        logger.warning(
            "school_university: could not classify name=%r; falling back to other=True",
            cat.name,
        )


def _map_religious_cultural(cat: ExtractionCategory, out: dict[str, Any]) -> None:
    name = cat.name or ""
    if _contains_any(name, _CHURCH_KEYWORDS):
        out["church"] = True
        out["chu_did"] = _did_str(cat)
        out["chu_n"] = cat.name
    elif _contains_any(name, _MOSQUE_KEYWORDS):
        out["mosque"] = True
        out["mos_did"] = _did_str(cat)
        out["mosque_n"] = cat.name
    elif _contains_any(name, _CEME_KEYWORDS):
        out["ceme"] = True
        out["ceme_did"] = _did_str(cat)
        out["ceme_n"] = cat.name
    elif _contains_any(name, _ARCHEO_KEYWORDS):
        out["archeo"] = True
        out["arch_did"] = _did_str(cat)
        out["arch_n"] = cat.name
    elif _contains_any(name, _RELEG_KEYWORDS):
        out["releg"] = True
        out["releg_did"] = _did_str(cat)
        out["releg_n"] = cat.name
    else:
        # other/other_type columns confirmed present in incident_detail.py
        out["other"] = True
        out["other_did"] = _did_str(cat)
        out["other_type"] = "religious_cultural_unclassified"
        logger.warning(
            "religious_cultural: could not classify name=%r; falling back to other=True",
            cat.name,
        )


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_CategoryHandler = Callable[[ExtractionCategory, dict[str, Any]], None]

_CATEGORY_HANDLERS: dict[ExtractionCategoryKey, _CategoryHandler] = {
    ExtractionCategoryKey.lebanese_army: _map_lebanese_army,
    ExtractionCategoryKey.unifil: _map_unifil,
    ExtractionCategoryKey.municipality: _map_municipality,
    ExtractionCategoryKey.hospital: _map_hospital,
    ExtractionCategoryKey.health_center: _map_health_center,
    ExtractionCategoryKey.press: _map_press,
    ExtractionCategoryKey.government_building: _map_government_building,
    ExtractionCategoryKey.vehicles: _map_vehicles,
    ExtractionCategoryKey.emergency_civil_defense: _map_emergency_civil_defense,
    ExtractionCategoryKey.crossings_other: _map_crossings_other,
    ExtractionCategoryKey.warning_classification: _map_warning_classification,
    ExtractionCategoryKey.school_university: _map_school_university,
    ExtractionCategoryKey.religious_cultural: _map_religious_cultural,
    ExtractionCategoryKey.road_bridge: _map_road_bridge,
    # casualty_demographics → handled via root ExtractionCasualties; skip here
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def map_categories(
    categories: dict[ExtractionCategoryKey, ExtractionCategory],
) -> dict[str, Any]:
    """Return a flat dict of incident_details column names → values.

    Only keys that are present in *categories* produce output entries.
    Absent categories contribute nothing; columns default to NULL in the DB.
    """
    out: dict[str, Any] = {}
    for key, category in categories.items():
        handler = _CATEGORY_HANDLERS.get(key)
        if handler is not None:
            handler(category, out)
        else:
            logger.debug(
                "No handler registered for ExtractionCategoryKey %r — skipping", key
            )
    return out


def compute_rollups(
    mapped: dict[str, Any],
    root_casualties: ExtractionCasualties,
) -> tuple[int | None, int | None]:
    """Compute (total_deaths, total_injuries) from category totals + root casualties.

    *root_casualties.deaths/injuries* are the general non-attributed civilian counts
    already written to Incident.deaths / Incident.injuries.  Returns (None, None)
    when no casualty data is present anywhere.
    """
    total_deaths = _safe_add(
        root_casualties.deaths,
        mapped.get("la_td"),
        mapped.get("un_td"),
        mapped.get("muni_td"),
        mapped.get("hosd"),
        mapped.get("hcd"),
        mapped.get("pressd"),
        mapped.get("gbd"),
        mapped.get("card"),
        mapped.get("emer_d"),
    )
    total_injuries = _safe_add(
        root_casualties.injuries,
        mapped.get("la_ti"),
        mapped.get("un_ti"),
        mapped.get("muni_ti"),
        mapped.get("hosi"),
        mapped.get("hci"),
        mapped.get("pressi"),
        mapped.get("gbi"),
        mapped.get("cari"),
        mapped.get("emer_i"),
    )
    return total_deaths, total_injuries
