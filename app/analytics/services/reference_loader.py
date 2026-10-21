"""Load analytics reference data: admin areas, village links, action families.

``plan_reference`` is read-only and returns what ``apply_reference`` would write,
so the script's dry-run and the real run share one code path.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.text_normalization import normalize_arabic_text

logger = logging.getLogger(__name__)

GEO_DIR = Path("frontend/public/geo")
FAMILIES_PATH = Path("Data/analytics/action_families.json")
GEO_FILES = (("mohafaza", "lb_mohafaza.geojson"), ("caza", "lb_caza.geojson"), ("village", "lb_village.geojson"))
LITIGE_NAME = "Litige"
CHEBAA_CODE = "74183"


@dataclass
class AreaRow:
    code: str
    level: str
    name_en: str | None
    name_ar: str | None
    parent_code: str | None
    caza_code: str | None
    mohafaza_code: str | None
    area_km2: float | None
    center_lat: float | None
    center_lon: float | None
    is_disputed: bool


@dataclass
class ConditionMapping:
    condition_id: int
    action_en: str
    action_ar: str
    family_code: str
    matched_by: str


@dataclass
class ReferencePlan:
    areas: list[AreaRow] = field(default_factory=list)
    families: list[dict[str, Any]] = field(default_factory=list)
    mappings: list[ConditionMapping] = field(default_factory=list)
    unmapped_conditions: list[tuple[int, str, str]] = field(default_factory=list)
    mapping_entries_without_condition: list[str] = field(default_factory=list)
    villages_linked: list[tuple[int, str]] = field(default_factory=list)
    villages_unlinked: list[tuple[int, int, str | None]] = field(default_factory=list)

    @property
    def counts_by_level(self) -> dict[str, int]:
        counts: dict[str, int] = {"mohafaza": 0, "caza": 0, "village": 0}
        for area in self.areas:
            counts[area.level] += 1
        return counts


def _walk_coords(geometry: dict[str, Any]):
    kind = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if kind == "Polygon":
        rings = [coords]
    elif kind == "MultiPolygon":
        rings = list(coords)
    else:
        return
    for polygon in rings:
        for ring in polygon:
            for point in ring:
                yield point[0], point[1]


def _bbox_center(geometry: dict[str, Any]) -> tuple[float | None, float | None]:
    xs: list[float] = []
    ys: list[float] = []
    for lon, lat in _walk_coords(geometry):
        xs.append(lon)
        ys.append(lat)
    if not xs:
        return None, None
    return (min(ys) + max(ys)) / 2, (min(xs) + max(xs)) / 2


def _as_code(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def read_geo_areas(geo_dir: Path = GEO_DIR) -> list[AreaRow]:
    rows: list[AreaRow] = []
    for level, filename in GEO_FILES:
        with (geo_dir / filename).open("r", encoding="utf-8") as handle:
            collection = json.load(handle)
        for feature in collection["features"]:
            props = feature["properties"]
            code = _as_code(props.get("code"))
            if code is None:
                raise ValueError(f"{filename}: feature without properties.code")
            lat, lon = props.get("center_lat"), props.get("center_lon")
            if lat is None or lon is None:
                lat, lon = _bbox_center(feature.get("geometry") or {})
            name_en = props.get("name_en")
            disputed = bool(props.get("disputed")) or name_en == LITIGE_NAME or code == CHEBAA_CODE
            if level == "mohafaza":
                parent, caza, mohafaza = None, None, code
            elif level == "caza":
                parent = _as_code(props.get("mohafaza_code"))
                caza, mohafaza = code, parent
            else:
                parent = _as_code(props.get("caza_code"))
                caza, mohafaza = parent, _as_code(props.get("mohafaza_code"))
            rows.append(AreaRow(
                code=code, level=level, name_en=name_en, name_ar=props.get("name_ar") or None,
                parent_code=parent, caza_code=caza, mohafaza_code=mohafaza,
                area_km2=props.get("area_sqkm"), center_lat=lat, center_lon=lon,
                is_disputed=disputed,
            ))
    codes = [row.code for row in rows]
    if len(codes) != len(set(codes)):
        raise ValueError("duplicate area codes across geojson files")
    return rows


def read_family_definitions(path: Path = FAMILIES_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    family_codes = [family["code"] for family in data["families"]]
    if len(family_codes) != len(set(family_codes)):
        raise ValueError("duplicate family codes in action_families.json")
    unknown = {c["family"] for c in data["conditions"]} - set(family_codes)
    if unknown:
        raise ValueError(f"action_families.json references unknown families: {sorted(unknown)}")
    return data


def _match_condition(
    condition: tuple[int, str, str],
    by_ar: dict[str, dict[str, str]],
    by_norm: dict[str, dict[str, str]],
    by_en: dict[str, dict[str, str]],
) -> tuple[dict[str, str], str] | None:
    _id, action_en, action_ar = condition
    if action_ar in by_ar:
        return by_ar[action_ar], "action_ar"
    normalized = normalize_arabic_text(action_ar or "")
    if normalized in by_norm:
        return by_norm[normalized], "action_ar (normalised)"
    key = (action_en or "").strip().casefold()
    if key in by_en:
        return by_en[key], "action_en"
    return None


def plan_reference(db: Session, geo_dir: Path = GEO_DIR, families_path: Path = FAMILIES_PATH) -> ReferencePlan:
    plan = ReferencePlan()
    plan.areas = read_geo_areas(geo_dir)
    definitions = read_family_definitions(families_path)
    plan.families = definitions["families"]

    by_ar = {c["action_ar"]: c for c in definitions["conditions"]}
    by_norm = {normalize_arabic_text(c["action_ar"]): c for c in definitions["conditions"]}
    by_en = {c["action_en"].strip().casefold(): c for c in definitions["conditions"]}
    used: set[str] = set()
    for row in db.execute(text("SELECT id, action_en, action_ar FROM conditions ORDER BY id")):
        condition = (int(row.id), row.action_en, row.action_ar)
        match = _match_condition(condition, by_ar, by_norm, by_en)
        if match is None:
            plan.unmapped_conditions.append(condition)
            continue
        entry, matched_by = match
        used.add(entry["action_ar"])
        plan.mappings.append(ConditionMapping(
            condition_id=condition[0], action_en=condition[1], action_ar=condition[2],
            family_code=entry["family"], matched_by=matched_by,
        ))
    plan.mapping_entries_without_condition = sorted(
        c["action_en"] for c in definitions["conditions"] if c["action_ar"] not in used
    )

    village_codes = {area.code for area in plan.areas if area.level == "village"}
    for row in db.execute(text("SELECT id, acs_code, ref_name_en FROM villages ORDER BY id")):
        code = str(row.acs_code)
        if code in village_codes:
            plan.villages_linked.append((int(row.id), code))
        else:
            plan.villages_unlinked.append((int(row.id), int(row.acs_code), row.ref_name_en))
    return plan


_UPSERT_AREA = text(
    """
    INSERT INTO admin_areas (code, level, name_en, name_ar, parent_code, caza_code, mohafaza_code,
                             area_km2, center_lat, center_lon, is_disputed)
    VALUES (:code, :level, :name_en, :name_ar, :parent_code, :caza_code, :mohafaza_code,
            :area_km2, :center_lat, :center_lon, :is_disputed)
    ON CONFLICT (code) DO UPDATE SET
        level = EXCLUDED.level, name_en = EXCLUDED.name_en, name_ar = EXCLUDED.name_ar,
        parent_code = EXCLUDED.parent_code, caza_code = EXCLUDED.caza_code,
        mohafaza_code = EXCLUDED.mohafaza_code, area_km2 = EXCLUDED.area_km2,
        center_lat = EXCLUDED.center_lat, center_lon = EXCLUDED.center_lon,
        is_disputed = EXCLUDED.is_disputed
    """
)
_UPSERT_FAMILY = text(
    """
    INSERT INTO action_families (code, name_en, name_ar, sort_order, is_air_violation, counts_in_headline)
    VALUES (:code, :name_en, :name_ar, :sort_order, :is_air_violation, :counts_in_headline)
    ON CONFLICT (code) DO UPDATE SET
        name_en = EXCLUDED.name_en, name_ar = EXCLUDED.name_ar, sort_order = EXCLUDED.sort_order,
        is_air_violation = EXCLUDED.is_air_violation, counts_in_headline = EXCLUDED.counts_in_headline
    """
)
_UPSERT_CONDITION_FAMILY = text(
    """
    INSERT INTO condition_families (condition_id, family_id)
    SELECT :condition_id, id FROM action_families WHERE code = :family_code
    ON CONFLICT (condition_id) DO UPDATE SET family_id = EXCLUDED.family_id
    """
)


def apply_reference(db: Session, plan: ReferencePlan) -> None:
    """Write ``plan``. Refuses (writes nothing) while a condition is unmapped."""
    if plan.unmapped_conditions:
        raise ValueError(
            "conditions without a family: "
            + ", ".join(f"{cid}:{en}" for cid, en, _ar in plan.unmapped_conditions)
        )
    order = {"mohafaza": 0, "caza": 1, "village": 2}
    for area in sorted(plan.areas, key=lambda a: order[a.level]):
        db.execute(_UPSERT_AREA, area.__dict__)
    db.execute(text(
        "UPDATE villages SET admin_area_code = acs_code::text "
        "WHERE acs_code::text IN (SELECT code FROM admin_areas WHERE level = 'village') "
        "AND admin_area_code IS DISTINCT FROM acs_code::text"
    ))
    for family in plan.families:
        db.execute(_UPSERT_FAMILY, family)
    for mapping in plan.mappings:
        db.execute(_UPSERT_CONDITION_FAMILY, {
            "condition_id": mapping.condition_id, "family_code": mapping.family_code,
        })
