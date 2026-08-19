from __future__ import annotations

import pytest

from app.llm.dtos.extraction_dto import (
    DidValue,
    ExtractionCasualties,
    ExtractionCategory,
    ExtractionCategoryKey,
    ExtractionVehicleDetails,
)
from app.news.services.category_mapper import compute_rollups, map_categories


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cat(
    *,
    did: DidValue | None = None,
    name: str | None = None,
    casualties: ExtractionCasualties | None = None,
    vehicles: ExtractionVehicleDetails | None = None,
) -> ExtractionCategory:
    return ExtractionCategory(
        did=did,
        name=name,
        casualties=casualties,
        vehicles=vehicles,
    )


def _cas(**kwargs: int | None) -> ExtractionCasualties:
    return ExtractionCasualties(**kwargs)


# ---------------------------------------------------------------------------
# lebanese_army
# ---------------------------------------------------------------------------


def test_la_category_maps_casualties_and_did() -> None:
    categories = {
        ExtractionCategoryKey.lebanese_army: _cat(
            did=DidValue.direct,
            casualties=_cas(
                male_deaths=3, male_injuries=1, female_deaths=1, female_injuries=2
            ),
        )
    }
    out = map_categories(categories)

    assert out["la"] is True
    assert out["la_did"] == "D"
    assert out["lam_d"] == 3
    assert out["lam_i"] == 1
    assert out["laf_d"] == 1
    assert out["laf_i"] == 2
    assert out["la_td"] == 4   # 3 + 1
    assert out["la_ti"] == 3   # 1 + 2


def test_la_indirect_did_maps_to_id_string() -> None:
    categories = {
        ExtractionCategoryKey.lebanese_army: _cat(did=DidValue.indirect)
    }
    out = map_categories(categories)
    assert out["la_did"] == "ID"


def test_la_absent_produces_no_la_keys() -> None:
    out = map_categories({})
    assert "la" not in out
    assert "la_did" not in out
    assert "la_td" not in out


def test_la_with_null_did_sets_la_did_none() -> None:
    categories = {
        ExtractionCategoryKey.lebanese_army: _cat(did=None)
    }
    out = map_categories(categories)
    assert out["la"] is True
    assert out["la_did"] is None


# ---------------------------------------------------------------------------
# hospital
# ---------------------------------------------------------------------------


def test_hospital_with_name_sets_hosp_hos_n_and_totals() -> None:
    categories = {
        ExtractionCategoryKey.hospital: _cat(
            did=DidValue.indirect,
            name="مستشفى الجنوب",
            casualties=_cas(male_deaths=2, female_deaths=1),
        )
    }
    out = map_categories(categories)

    assert out["hosp"] is True
    assert out["hos_did"] == "ID"
    assert out["hos_n"] == "مستشفى الجنوب"
    assert out["hosm_d"] == 2
    assert out["hosf_d"] == 1
    assert out["hosd"] == 3   # 2 + 1


# ---------------------------------------------------------------------------
# school_university
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["مدرسة الرسالة", "Public School", "ثانوية النبطية"])
def test_school_keywords_classify_as_school(name: str) -> None:
    categories = {ExtractionCategoryKey.school_university: _cat(name=name)}
    out = map_categories(categories)

    assert out["school"] is True
    assert out["school_name"] == name
    assert "uni" not in out
    assert "other" not in out


def test_university_keyword_classifies_as_uni() -> None:
    categories = {
        ExtractionCategoryKey.school_university: _cat(
            did=DidValue.direct, name="الجامعة اللبنانية"
        )
    }
    out = map_categories(categories)

    assert out["uni"] is True
    assert out["uni_did"] == "D"
    assert out["uni_name"] == "الجامعة اللبنانية"
    assert "school" not in out


def test_ambiguous_school_university_name_falls_back_to_other() -> None:
    categories = {
        ExtractionCategoryKey.school_university: _cat(name="مبنى تعليمي غير محدد")
    }
    out = map_categories(categories)

    assert out.get("other") is True
    assert out.get("other_type") == "school_university_unclassified"
    assert "school" not in out
    assert "uni" not in out


# ---------------------------------------------------------------------------
# warning_classification
# ---------------------------------------------------------------------------


def test_warning_classification_sets_warning_flag() -> None:
    categories = {
        ExtractionCategoryKey.warning_classification: _cat(name="warning")
    }
    out = map_categories(categories)
    assert out.get("warning") is True
    assert "no_warning" not in out


def test_warning_classification_no_warning_checked_first() -> None:
    categories = {
        ExtractionCategoryKey.warning_classification: _cat(name="no_warning")
    }
    out = map_categories(categories)
    assert out.get("no_warning") is True
    assert "warning" not in out


# ---------------------------------------------------------------------------
# vehicles
# ---------------------------------------------------------------------------


def test_vehicles_legacy_shape_defaults_to_car() -> None:
    categories = {
        ExtractionCategoryKey.vehicles: _cat(
            casualties=_cas(male_injuries=1),
        )
    }
    out = map_categories(categories)

    assert out["car"] is True
    assert out["carm_i"] == 1
    assert "con_veh" not in out
    assert "total_con" not in out


def test_vehicles_maps_construction_subtypes_and_total_con() -> None:
    categories = {
        ExtractionCategoryKey.vehicles: _cat(
            vehicles=ExtractionVehicleDetails(
                con_veh=True,
                excavator=True,
                bulldozer=True,
                con_d=1,
            ),
        )
    }
    out = map_categories(categories)

    assert out["con_veh"] is True
    assert out["excavator"] is True
    assert out["bulldozer"] is True
    assert out["con_d"] == 1
    assert out["total_con"] == 2
    assert "car" not in out


def test_vehicles_construction_gate_keeps_subtypes_null_when_absent() -> None:
    categories = {
        ExtractionCategoryKey.vehicles: _cat(
            vehicles=ExtractionVehicleDetails(car=True),
        )
    }
    out = map_categories(categories)

    assert out["car"] is True
    assert "con_veh" not in out
    assert "total_con" not in out


# ---------------------------------------------------------------------------
# compute_rollups
# ---------------------------------------------------------------------------


def test_rollup_sums_la_hospital_and_root_casualties() -> None:
    categories = {
        ExtractionCategoryKey.lebanese_army: _cat(
            casualties=_cas(
                male_deaths=2, female_deaths=1,
                male_injuries=1, female_injuries=1,
            )
        ),
        ExtractionCategoryKey.hospital: _cat(
            casualties=_cas(
                male_deaths=1, female_deaths=0,
                male_injuries=2, female_injuries=0,
            )
        ),
    }
    mapped = map_categories(categories)
    root = _cas(deaths=5, injuries=3)
    td, ti = compute_rollups(mapped, root)

    # la_td=3, hosd=1, root.deaths=5  →  9
    assert td == 9
    # la_ti=2, hosi=2, root.injuries=3  →  7
    assert ti == 7


def test_rollup_returns_none_when_all_inputs_are_none() -> None:
    mapped = map_categories({})
    root = ExtractionCasualties()
    td, ti = compute_rollups(mapped, root)

    assert td is None
    assert ti is None


def test_vehicles_maps_children_casualties() -> None:
    categories = {
        ExtractionCategoryKey.vehicles: _cat(
            vehicles=ExtractionVehicleDetails(car=True),
            casualties=_cas(children_deaths=1, children_injuries=2),
        )
    }
    out = map_categories(categories)

    assert out["car"] is True
    assert out["carc_d"] == 1
    assert out["carc_i"] == 2


def test_road_bridge_maps_road_name_and_blocked() -> None:
    categories = {
        ExtractionCategoryKey.road_bridge: _cat(
            did=DidValue.direct,
            name="الطريق بين شبعا وكفرشوبا قطع",
        )
    }
    out = map_categories(categories)

    assert out["road"] is True
    assert out["road_d_id"] == "D"
    assert out["road_name"] == "الطريق بين شبعا وكفرشوبا قطع"
    assert out["road_blocked"] is True


def test_crossings_other_maps_water_infrastructure() -> None:
    categories = {
        ExtractionCategoryKey.crossings_other: _cat(
            did=DidValue.indirect,
            name="محطة مياه بلدة",
        )
    }
    out = map_categories(categories)

    assert out["water"] is True
    assert out["water_did"] == "ID"
    assert out["water_type"] == "محطة مياه بلدة"


def test_warning_classification_maps_building_flag() -> None:
    categories = {
        ExtractionCategoryKey.warning_classification: _cat(name="building")
    }
    out = map_categories(categories)
    assert out["building"] is True


def test_rollup_none_components_are_skipped_not_treated_as_zero() -> None:
    # Only root injuries present; LA category has no casualties object
    categories = {
        ExtractionCategoryKey.lebanese_army: _cat()   # no casualties → no la_td
    }
    mapped = map_categories(categories)
    root = _cas(deaths=None, injuries=4)
    td, ti = compute_rollups(mapped, root)

    assert td is None
    assert ti == 4
