from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any, Protocol

from app.llm.dtos.extraction_dto import (
    ExtractionCasualties,
    ExtractionCategory,
    ExtractionCategoryKey,
)

logger = logging.getLogger(__name__)

CATEGORY_CASUALTY_FIELDS = frozenset(
    {
        "lam_d",
        "lam_i",
        "laf_d",
        "laf_i",
        "la_td",
        "la_ti",
        "unm_d",
        "unm_i",
        "unf_d",
        "unf_i",
        "un_td",
        "un_ti",
        "munim_d",
        "munim_i",
        "munif_d",
        "munif_i",
        "muni_td",
        "muni_ti",
        "hosm_d",
        "hosm_i",
        "hosf_d",
        "hosf_i",
        "hosd",
        "hosi",
        "hcm_d",
        "hcm_i",
        "hcf_d",
        "hcf_i",
        "hcd",
        "hci",
        "pressm_d",
        "pressm_i",
        "pressf_d",
        "pressf_i",
        "pressd",
        "pressi",
        "gbm_d",
        "gbm_i",
        "gbf_d",
        "gbf_i",
        "gbd",
        "gbi",
        "carm_d",
        "carm_i",
        "carf_d",
        "carf_i",
        "carc_d",
        "carc_i",
        "cara_d",
        "cara_i",
        "card",
        "cari",
        "moto_d",
        "moto_i",
        "con_d",
        "con_i",
        "emer_d",
        "emer_i",
        "olives_trees_d",
    }
)


def suppress_category_casualties(
    mapped: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    suppressed = any(
        mapped.get(field) is not None for field in CATEGORY_CASUALTY_FIELDS
    )
    if not suppressed:
        return mapped, False
    return (
        {
            key: (None if key in CATEGORY_CASUALTY_FIELDS else value)
            for key, value in mapped.items()
        },
        True,
    )


class _EmergencyOrgMatcher(Protocol):
    def match(self, text: str | None) -> Any: ...

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
# Vehicle language on emergency-response subjects (ambulance / civil-defense cars).
_EMERGENCY_VEHICLE_KEYWORDS: tuple[str, ...] = (
    "سيارة",
    "سيارات",
    "آلية إسعاف",
    "آليات إسعاف",
)
_ARABIC_DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_VEHICLE_COUNT_RE = re.compile(
    r"(\d+)\s*(?:سيارة|سيارات)|(?:سيارة|سيارات)\s*(\d+)"
)

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


def _casualty_total(
    explicit_total: int | None,
    *demographic_values: int | None,
) -> int | None:
    """Use explicit entity totals when present; otherwise sum demographics."""
    if explicit_total is not None:
        return explicit_total
    return _safe_add(*demographic_values)


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
        out["la_td"] = _casualty_total(
            c.deaths, c.male_deaths, c.female_deaths, c.children_deaths
        )
        out["la_ti"] = _casualty_total(
            c.injuries, c.male_injuries, c.female_injuries, c.children_injuries
        )


def _map_unifil(cat: ExtractionCategory, out: dict[str, Any]) -> None:
    out["unifil"] = True
    out["un_did"] = _did_str(cat)
    c = cat.casualties
    if c is not None:
        out["unm_d"] = c.male_deaths
        out["unm_i"] = c.male_injuries
        out["unf_d"] = c.female_deaths
        out["unf_i"] = c.female_injuries
        out["un_td"] = _casualty_total(
            c.deaths, c.male_deaths, c.female_deaths, c.children_deaths
        )
        out["un_ti"] = _casualty_total(
            c.injuries, c.male_injuries, c.female_injuries, c.children_injuries
        )


def _map_municipality(cat: ExtractionCategory, out: dict[str, Any]) -> None:
    out["muni"] = True
    out["muni_did"] = _did_str(cat)
    c = cat.casualties
    if c is not None:
        out["munim_d"] = c.male_deaths
        out["munim_i"] = c.male_injuries
        out["munif_d"] = c.female_deaths
        out["munif_i"] = c.female_injuries
        out["muni_td"] = _casualty_total(
            c.deaths, c.male_deaths, c.female_deaths, c.children_deaths
        )
        out["muni_ti"] = _casualty_total(
            c.injuries, c.male_injuries, c.female_injuries, c.children_injuries
        )


def _hospital_casualty_attribution_allowed(cat: ExtractionCategory) -> bool:
    """Require DID or an explicit hospital-like name before writing HosD/HosI.

    Presence alone can still gate ``hosp=True`` elsewhere; bare generic deaths
    on a nameless hospital category are usually vehicle/civilian bleed.
    """
    if cat.did is not None:
        return True
    name = (cat.name or "").strip()
    if not name:
        return False
    return _contains_any(name, _HOSPITAL_NAME_KEYWORDS)


_HOSPITAL_NAME_KEYWORDS: frozenset[str] = frozenset(
    {"مستشفى", "مشفى", "hospital", "عيادة", "مستوصف"}
)


def _map_hospital(cat: ExtractionCategory, out: dict[str, Any]) -> None:
    out["hosp"] = True
    out["hos_did"] = _did_str(cat)
    out["hos_n"] = cat.name
    c = cat.casualties
    if c is not None and _hospital_casualty_attribution_allowed(cat):
        out["hosm_d"] = c.male_deaths
        out["hosm_i"] = c.male_injuries
        out["hosf_d"] = c.female_deaths
        out["hosf_i"] = c.female_injuries
        out["hosd"] = _casualty_total(
            c.deaths, c.male_deaths, c.female_deaths, c.children_deaths
        )
        out["hosi"] = _casualty_total(
            c.injuries, c.male_injuries, c.female_injuries, c.children_injuries
        )


def _map_health_center(cat: ExtractionCategory, out: dict[str, Any]) -> None:
    out["hc"] = True
    out["hc_did"] = _did_str(cat)
    c = cat.casualties
    if c is not None:
        out["hcm_d"] = c.male_deaths
        out["hcm_i"] = c.male_injuries
        out["hcf_d"] = c.female_deaths
        out["hcf_i"] = c.female_injuries
        out["hcd"] = _casualty_total(
            c.deaths, c.male_deaths, c.female_deaths, c.children_deaths
        )
        out["hci"] = _casualty_total(
            c.injuries, c.male_injuries, c.female_injuries, c.children_injuries
        )


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
        out["pressd"] = _casualty_total(
            c.deaths, c.male_deaths, c.female_deaths, c.children_deaths
        )
        out["pressi"] = _casualty_total(
            c.injuries, c.male_injuries, c.female_injuries, c.children_injuries
        )


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
        out["gbd"] = _casualty_total(
            c.deaths, c.male_deaths, c.female_deaths, c.children_deaths
        )
        out["gbi"] = _casualty_total(
            c.injuries, c.male_injuries, c.female_injuries, c.children_injuries
        )


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
    # Genderless vehicle tolls belong in the anonymous buckets (spreadsheet
    # Anonymous_CD / Anonymous_CI). CarD / CarI remain the automated sum.
    has_death_demographics = any(
        value is not None
        for value in (c.male_deaths, c.female_deaths, c.children_deaths)
    )
    has_injury_demographics = any(
        value is not None
        for value in (c.male_injuries, c.female_injuries, c.children_injuries)
    )
    if c.deaths is not None and not has_death_demographics:
        out["cara_d"] = c.deaths
    if c.injuries is not None and not has_injury_demographics:
        out["cara_i"] = c.injuries
    out["card"] = _safe_add(
        out.get("carm_d"),
        out.get("carf_d"),
        out.get("carc_d"),
        out.get("cara_d"),
    )
    out["cari"] = _safe_add(
        out.get("carm_i"),
        out.get("carf_i"),
        out.get("carc_i"),
        out.get("cara_i"),
    )


def _extract_vehicle_count(text: str) -> int | None:
    """Best-effort count next to سيارة/سيارات; returns None when no numeral found."""
    normalized = text.translate(_ARABIC_DIGIT_MAP)
    match = _VEHICLE_COUNT_RE.search(normalized)
    if match is None:
        return None
    raw = match.group(1) or match.group(2)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _emergency_vehicle_signals(
    cat: ExtractionCategory,
    categories: dict[ExtractionCategoryKey, ExtractionCategory],
) -> tuple[bool | None, int | None]:
    """Derive ``e_cars`` / ``car_nbr`` from the emergency category and co-present vehicles."""
    car_hit = False
    count: int | None = None

    if cat.vehicles is not None and cat.vehicles.car:
        car_hit = True
        count = 1

    vehicles_cat = categories.get(ExtractionCategoryKey.vehicles)
    if (
        vehicles_cat is not None
        and vehicles_cat.vehicles is not None
        and vehicles_cat.vehicles.car
    ):
        car_hit = True
        if count is None:
            count = 1

    name = cat.name or ""
    if any(term in name for term in _EMERGENCY_VEHICLE_KEYWORDS):
        car_hit = True
        parsed = _extract_vehicle_count(name)
        if parsed is not None:
            count = parsed
        elif count is None:
            count = 1

    if not car_hit:
        return None, None
    return True, count if count is not None else 1


def _map_emergency_civil_defense(
    cat: ExtractionCategory,
    out: dict[str, Any],
    *,
    categories: dict[ExtractionCategoryKey, ExtractionCategory],
    org_matcher: _EmergencyOrgMatcher | None,
) -> None:
    out["emer"] = True
    c = cat.casualties
    if c is not None:
        out["emer_d"] = c.deaths
        out["emer_i"] = c.injuries

    raw_name = (cat.name or "").strip() or None
    if raw_name:
        # Always preserve extracted text; overwrite with the canonical Arabic
        # name only on a confident (>=0.6) controlled-vocabulary match.
        emer_rela = raw_name
        if org_matcher is not None:
            match = org_matcher.match(raw_name)
            if match.status == "matched" and match.matched_name_ar:
                emer_rela = match.matched_name_ar
        out["emer_rela"] = emer_rela

    e_cars, car_nbr = _emergency_vehicle_signals(cat, categories)
    if e_cars is not None:
        out["e_cars"] = e_cars
    if car_nbr is not None:
        out["car_nbr"] = car_nbr


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
    # emergency_civil_defense is handled specially in map_categories (needs matcher).
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
    *,
    emergency_org_matcher: _EmergencyOrgMatcher | None = None,
) -> dict[str, Any]:
    """Return a flat dict of incident_details column names → values.

    Only keys that are present in *categories* produce output entries.
    Absent categories contribute nothing; columns default to NULL in the DB.

    When ``emergency_org_matcher`` is supplied, a confident match replaces the
    raw ``emergency_civil_defense.name`` with the canonical ``name_ar`` in
    ``emer_rela``; low-confidence / unmatched names are still written as free
    text so extracted affiliation is never silently dropped.
    """
    out: dict[str, Any] = {}
    for key, category in categories.items():
        if key == ExtractionCategoryKey.emergency_civil_defense:
            _map_emergency_civil_defense(
                category,
                out,
                categories=categories,
                org_matcher=emergency_org_matcher,
            )
            continue
        handler = _CATEGORY_HANDLERS.get(key)
        if handler is not None:
            handler(category, out)
        else:
            logger.debug(
                "No handler registered for ExtractionCategoryKey %r — skipping", key
            )
    return out


_ENTITY_DEATH_FIELDS: tuple[str, ...] = (
    "la_td",
    "un_td",
    "muni_td",
    "hosd",
    "hcd",
    "pressd",
    "gbd",
    "card",
    "emer_d",
)
_ENTITY_INJURY_FIELDS: tuple[str, ...] = (
    "la_ti",
    "un_ti",
    "muni_ti",
    "hosi",
    "hci",
    "pressi",
    "gbi",
    "cari",
    "emer_i",
)


def _sum_mapped(mapped: dict[str, Any], fields: tuple[str, ...]) -> int | None:
    values = [mapped.get(field) for field in fields]
    if all(value is None for value in values):
        return None
    return sum(int(value) for value in values if isinstance(value, int))


def reconcile_root_vs_entity_casualties(
    mapped: dict[str, Any],
    root_casualties: ExtractionCasualties,
) -> ExtractionCasualties:
    """Drop root deaths/injuries that duplicate gated-entity subtotals.

    ``Total_D`` / ``Total_Inj`` sum root + entity fields. When Tier 1 kept the
    same toll on root while Tier 2 also wrote it into ``CarD``/``HosD``/etc.,
    clear the root copy so rollups do not double-count.

    Only exact duplicates are cleared (root == entity sum). A larger or
    smaller root is treated as additional/unrelated general casualties.
    """
    entity_deaths = _sum_mapped(mapped, _ENTITY_DEATH_FIELDS)
    entity_injuries = _sum_mapped(mapped, _ENTITY_INJURY_FIELDS)
    deaths = root_casualties.deaths
    injuries = root_casualties.injuries
    if (
        isinstance(deaths, int)
        and isinstance(entity_deaths, int)
        and entity_deaths > 0
        and deaths == entity_deaths
    ):
        deaths = None
    if (
        isinstance(injuries, int)
        and isinstance(entity_injuries, int)
        and entity_injuries > 0
        and injuries == entity_injuries
    ):
        injuries = None
    if deaths == root_casualties.deaths and injuries == root_casualties.injuries:
        return root_casualties
    return root_casualties.model_copy(update={"deaths": deaths, "injuries": injuries})


def compute_rollups(
    mapped: dict[str, Any],
    root_casualties: ExtractionCasualties,
) -> tuple[int | None, int | None]:
    """Compute (total_deaths, total_injuries) from category totals + root casualties.

    *root_casualties.deaths/injuries* are the general non-attributed civilian counts
    already written to Incident.deaths / Incident.injuries.  Returns (None, None)
    when no casualty data is present anywhere.
    """
    root = reconcile_root_vs_entity_casualties(mapped, root_casualties)
    total_deaths = _safe_add(
        root.deaths,
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
        root.injuries,
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
