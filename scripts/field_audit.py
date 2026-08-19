"""One-off field inventory audit across DB / mapper / serializer / frontend."""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "phase2-extraction-testing"))

from build_answer_key import CASUALTY_FIELDS, CATEGORY_GROUPS  # noqa: E402

EXCEL_TO_DB: dict[str, str] = {
    "LA_TD": "la_td",
    "LA_TI": "la_ti",
    "UN_TD": "un_td",
    "UN_TI": "un_ti",
    "MUNI_TD": "muni_td",
    "MUNI_TI": "muni_ti",
    "HosD": "hosd",
    "HosI": "hosi",
    "HCD": "hcd",
    "HCI": "hci",
    "PressD": "pressd",
    "PressI": "pressi",
    "GBD": "gbd",
    "GBI": "gbi",
    "CarD": "card",
    "CarI": "cari",
    "Total_Con": "total_con",
    "MUNI_Empl": "muni_empl",
    "MUNI_Bldg": "muni_bldg",
    "LA_Bldg": "la_bldg",
    "LA_V": "la_v",
    "UN_Bldg": "un_bldg",
    "UN_V": "un_v",
    "Sch_DID": "sch_did",
    "School_Name": "school_name",
    "School_Damage_Level": "sch_damage_level",
    "Uni_DID": "uni_did",
    "Uni_Name": "uni_name",
    "Chu_DID": "chu_did",
    "Chu_N": "chu_n",
    "Mos_DID": "mos_did",
    "Mosque_N": "mosque_n",
    "Ceme_DID": "ceme_did",
    "Ceme_N": "ceme_n",
    "Releg_DID": "releg_did",
    "Releg_N": "releg_n",
    "Arch_DID": "arch_did",
    "Arch_N": "arch_n",
    "Hos_DID": "hos_did",
    "Hos_Status": "hos_status",
    "Hos_N": "hos_n",
    "Hos_Damage_Level": "hos_damage_level",
    "Nbr_Evap": "nbr_evap",
    "HosM_D": "hosm_d",
    "HosM_I": "hosm_i",
    "HosF_D": "hosf_d",
    "HosF_I": "hosf_i",
    "HC_Rela": "hc_rela",
    "HC_DID": "hc_did",
    "HC_Damage_Level": "hc_damage_level",
    "HCM_D": "hcm_d",
    "HCM_I": "hcm_i",
    "HCF_D": "hcf_d",
    "HCF_I": "hcf_i",
    "E_Cars": "e_cars",
    "Car_Nbr": "car_nbr",
    "Emer_Rela": "emer_rela",
    "Emer_D": "emer_d",
    "Emer_I": "emer_i",
    "Press_DID": "press_did",
    "PressM_D": "pressm_d",
    "PressM_I": "pressm_i",
    "PressF_D": "pressf_d",
    "PressF_I": "pressf_i",
    "Gov_Bui": "gov_bui",
    "Gov_N": "gov_n",
    "GB_DID": "gb_did",
    "GBM_D": "gbm_d",
    "GBM_I": "gbm_i",
    "GBF_D": "gbf_d",
    "GBF_I": "gbf_i",
    "Road_D_ID": "road_d_id",
    "Road_Blocked": "road_blocked",
    "Road_Name": "road_name",
    "Bridge_Blocked": "bridge_blocked",
    "Bridge_Name": "bridge_name",
    "CarM_D": "carm_d",
    "CarM_I": "carm_i",
    "CarF_D": "carf_d",
    "CarF_I": "carf_i",
    "CarC_D": "carc_d",
    "CarC_I": "carc_i",
    "Moto_DID": "moto_did",
    "Moto_D": "moto_d",
    "Moto_I": "moto_i",
    "Con_Veh": "con_veh",
    "Con_D": "con_d",
    "Con_I": "con_i",
    "Drone_F": "drone_f",
    "Water_DID": "water_did",
    "Water_Type": "water_type",
    "Electric_DID": "electric_did",
    "Electric_Type": "electric_type",
    "Olives_Trees_D": "olives_trees_d",
    "MJ_DID": "mj_did",
    "Other_DID": "other_did",
    "Other_Type": "other_type",
    "Other_D": "other_d",
    "Other_I": "other_i",
    "No_Warning": "no_warning",
    "Mjnoub": "mjnoub",
    "Total_D": "total_deaths",
    "Total_Inj": "total_injuries",
    "Death": "deaths",
    "Injuries": "injuries",
    "Male_D": "male_d",
    "Male_I": "male_i",
    "female_D": "female_d",
    "female_I": "female_i",
    "Children_D": "children_d",
    "Children_I": "children_i",
}

SECTION_FOR_FIELD: dict[str, str] = {}
FIELD_TYPE: dict[str, str] = {}

AUTOMATED = {
    "la_td", "la_ti", "un_td", "un_ti", "muni_td", "muni_ti",
    "hosd", "hosi", "hcd", "hci", "pressd", "pressi", "gbd", "gbi",
    "card", "cari", "total_con", "total_deaths", "total_injuries",
}
DID_FIELDS = {f for f in EXCEL_TO_DB.values() if f.endswith("_did") or f.endswith("_d_id")}
FLAG_SUFFIX = True


def excel_to_db(name: str) -> str:
    return EXCEL_TO_DB.get(name, name.lower())


def build_canonical() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    section_map = {
        "army": "Lebanese Army (LA)",
        "unifil": "UNIFIL",
        "municipality": "Municipality",
        "school_university": "School / University",
        "religious_cultural": "Religious & cultural",
        "hospital": "Hospital",
        "health_center": "Health Center",
        "emergency_civil_defense": "Emergency / Civil Defense",
        "press": "Press",
        "government_building": "Government building",
        "road_bridge": "Road / Bridge",
        "vehicles": "Vehicles",
        "crossings_other": "Crossings & other",
        "warning_classification": "Warning & classification",
    }
    for key, group in CATEGORY_GROUPS.items():
        section = section_map[key]
        for excel_name in group["fields"]:
            db_name = excel_to_db(excel_name)
            if db_name in AUTOMATED:
                ftype = "Automated"
            elif db_name in DID_FIELDS or db_name.endswith("_did") or db_name.endswith("_d_id"):
                ftype = "Direct-Indirect"
            elif db_name.endswith(("_d", "_i")) and db_name not in AUTOMATED:
                ftype = "Count"
            elif db_name in {
                "school_name", "uni_name", "chu_n", "mosque_n", "ceme_n", "releg_n", "arch_n",
                "hos_status", "hos_n", "hos_damage_level", "sch_damage_level", "hc_rela",
                "hc_damage_level", "car_nbr", "emer_rela", "channel", "gov_n", "road_name",
                "bridge_name", "water_type", "electric_type", "other_type", "gov_bui",
            }:
                ftype = "Free text"
            else:
                ftype = "Flag"
            rows.append((db_name, section, ftype))
    rows.append(("male_d", "Casualty demographics", "Count"))
    rows.append(("male_i", "Casualty demographics", "Count"))
    rows.append(("female_d", "Casualty demographics", "Count"))
    rows.append(("female_i", "Casualty demographics", "Count"))
    rows.append(("children_d", "Casualty demographics", "Count"))
    rows.append(("children_i", "Casualty demographics", "Count"))
    rows.append(("deaths", "Casualty demographics", "Count"))
    rows.append(("injuries", "Casualty demographics", "Count"))
    rows.append(("total_deaths", "Casualty demographics", "Automated"))
    rows.append(("total_injuries", "Casualty demographics", "Automated"))
    for extra, ftype in [
        ("obs_duties", "Flag"), ("isf_gs", "Flag"), ("fire", "Flag"),
        ("arrested", "Count"), ("lib_y_n", "Free text"),
    ]:
        rows.append((extra, "Casualty demographics", ftype))
    return rows


API_TO_DB = {
    "child_d": "children_d", "child_i": "children_i", "hc_m_d": "hcm_d", "hc_m_i": "hcm_i",
    "hc_f_d": "hcf_d", "hc_f_i": "hcf_i", "press_m_d": "pressm_d", "press_m_i": "pressm_i",
    "press_f_d": "pressf_d", "press_f_i": "pressf_i", "muni_m_d": "munim_d", "muni_m_i": "munim_i",
    "muni_f_d": "munif_d", "muni_f_i": "munif_i", "gb_m_d": "gbm_d", "gb_m_i": "gbm_i",
    "gb_f_d": "gbf_d", "gb_f_i": "gbf_i", "car_d": "card", "car_i": "cari", "car_m_d": "carm_d",
    "car_m_i": "carm_i", "car_f_d": "carf_d", "car_f_i": "carf_i", "car_c_d": "carc_d", "car_c_i": "carc_i",
    "hos_m_d": "hosm_d", "hos_m_i": "hosm_i", "hos_f_d": "hosf_d", "hos_f_i": "hosf_i",
}

# LLM can produce via ExtractionCategory / vehicles / root casualties
LLM_MAPPABLE = {
    "la", "la_did", "lam_d", "lam_i", "laf_d", "laf_i", "la_td", "la_ti",
    "unifil", "un_did", "unm_d", "unm_i", "unf_d", "unf_i", "un_td", "un_ti",
    "muni", "muni_did", "munim_d", "munim_i", "munif_d", "munif_i", "muni_td", "muni_ti",
    "hosp", "hos_did", "hos_n", "hosm_d", "hosm_i", "hosf_d", "hosf_i", "hosd", "hosi",
    "hc", "hc_did", "hcm_d", "hcm_i", "hcf_d", "hcf_i", "hcd", "hci",
    "press", "press_did", "channel", "pressm_d", "pressm_i", "pressf_d", "pressf_i", "pressd", "pressi",
    "gov", "gb_did", "gov_n", "gbm_d", "gbm_i", "gbf_d", "gbf_i", "gbd", "gbi",
    "emer", "emer_d", "emer_i",
    "school", "sch_did", "school_name", "uni", "uni_did", "uni_name",
    "church", "chu_did", "chu_n", "mosque", "mos_did", "mosque_n",
    "ceme", "ceme_did", "ceme_n", "releg", "releg_did", "releg_n", "archeo", "arch_did", "arch_n",
    "crossing", "no_warning", "warning",
    "car", "card", "cari", "carm_d", "carm_i", "carf_d", "carf_i", "carc_d", "carc_i",
    "moto", "moto_did", "moto_d", "moto_i", "con_veh", "con_d", "con_i",
    "excavator", "bulldozer", "camion", "bobcat", "tracteur", "total_con",
    "male_d", "male_i", "female_d", "female_i", "children_d", "children_i", "deaths", "injuries",
    "other", "other_type", "other_did",
}


def main() -> None:
    model_text = (PROJECT_ROOT / "app/news/models/incident_detail.py").read_text(encoding="utf-8")
    db_cols = {
        m.group(1)
        for m in re.finditer(r"^\s+(\w+):\s+Mapped", model_text, re.M)
        if m.group(1) != "incident"
    }

    mapper_text = (PROJECT_ROOT / "app/news/services/category_mapper.py").read_text(encoding="utf-8")
    mapper_keys = set(re.findall(r'out\["(\w+)"\]', mapper_text))

    ser_text = (PROJECT_ROOT / "app/news/services/incident_detail_category_serializer.py").read_text(
        encoding="utf-8"
    )
    ser_fields = set(re.findall(r'"(\w+)"', ser_text.split("_CATEGORY_SECTIONS")[1].split("def _db_column")[0]))
    ser_db = {API_TO_DB.get(f, f) for f in ser_fields}

    schema_text = (PROJECT_ROOT / "frontend/src/features/news/incidentSchema.ts").read_text(encoding="utf-8")
    fe_fields = set(re.findall(r'(?:flag|count|text|deaths|injuries|did)\("(\w+)"\)', schema_text))
    fe_db = {API_TO_DB.get(f, f) for f in fe_fields}

    canonical = build_canonical()
    seen = set()
    unique_rows = []
    for row in canonical:
        if row[0] not in seen:
            seen.add(row[0])
            unique_rows.append(row)

    print(f"field|section|type|db|llm|mapper|serializer|frontend|gap")
    gaps = []
    for field, section, ftype in sorted(unique_rows, key=lambda r: (r[1], r[0])):
        in_db = field in db_cols or field in {"deaths", "injuries", "total_deaths", "total_injuries"}
        in_llm = field in LLM_MAPPABLE or ftype == "Automated"
        in_mapper = field in mapper_keys or field in {"male_d", "male_i", "female_d", "female_i", "children_d", "children_i", "deaths", "injuries", "total_deaths", "total_injuries"}
        in_ser = field in ser_db or field in {"male_d", "male_i", "female_d", "female_i", "children_d", "children_i"}
        in_fe = field in fe_db or field in {"male_d", "male_i", "female_d", "female_i", "children_d", "children_i", "deaths", "injuries", "total_deaths", "total_injuries"}
        gap_parts = []
        if not in_db and field not in {"deaths", "injuries", "total_deaths", "total_injuries"}:
            gap_parts.append("no-db-column")
        if not in_llm and ftype not in ("Automated",):
            gap_parts.append("llm")
        if not in_mapper and field not in {"male_d", "male_i", "female_d", "female_i", "children_d", "children_i", "deaths", "injuries", "total_deaths", "total_injuries", "obs_duties", "isf_gs", "fire", "arrested", "lib_y_n"}:
            gap_parts.append("mapper")
        if not in_ser and field not in {"male_d", "male_i", "female_d", "female_i", "children_d", "children_i", "deaths", "injuries", "total_deaths", "total_injuries", "hosd", "hosi", "hcd", "hci", "pressd", "pressi", "gbd", "gbi"}:
            gap_parts.append("serializer")
        if not in_fe and field not in {"hosd", "hosi", "hcd", "hci", "pressd", "pressi", "gbd", "gbi"}:
            gap_parts.append("frontend")
        gap = ";".join(gap_parts) if gap_parts else "-"
        if gap != "-":
            gaps.append((field, section, gap))
        print(f"{field}|{section}|{ftype}|{'Y' if in_db else 'N'}|{'Y' if in_llm else 'N'}|{'Y' if in_mapper else 'N'}|{'Y' if in_ser else 'N'}|{'Y' if in_fe else 'N'}|{gap}")

    print(f"\nTOTAL_FIELDS={len(unique_rows)} GAPS={len(gaps)}")
    print("\n=== DRIFT: code fields not in canonical ===")
    for f in sorted(db_cols - seen):
        print(f"  {f}")

    print("\n=== §7 KNOWN ISSUES ===")
    print("Muni_employees vs muni_empl: DB/serializer/frontend use muni_empl; Excel uses MUNI_Empl")
    print("Dam_Level duplicate: Excel Hos_Damage_Level + HC_Damage_Level -> sch_damage_level, hos_damage_level, hc_damage_level in code")
    print("Blocked duplicate: Excel Road_Blocked + Bridge_Blocked -> road_blocked, bridge_blocked in code")


if __name__ == "__main__":
    main()
