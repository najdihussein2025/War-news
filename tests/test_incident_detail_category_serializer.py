from __future__ import annotations

from uuid import uuid4

from app.news.models.incident_detail import IncidentDetail
from app.news.services.incident_detail_category_serializer import (
    serialize_category_section,
    serialize_incident_category_sections,
)


def test_serialize_lebanese_army_section_when_gate_active() -> None:
    detail = IncidentDetail(
        incident_id=uuid4(),
        la=True,
        la_did="D",
        lam_d=1,
        laf_i=2,
        la_td=1,
        la_ti=2,
    )

    section = serialize_category_section(detail, "lebanese_army")

    assert section is not None
    assert section["la"] == 1
    assert section["la_did"] == "D"
    assert section["lam_d"] == 1
    assert section["la_td"] == 1


def test_serialize_health_center_hidden_when_gate_inactive() -> None:
    detail = IncidentDetail(
        incident_id=uuid4(),
        hc=False,
        hcm_d=1,
    )

    assert serialize_category_section(detail, "health_center") is None


def test_serialize_hospital_uses_api_field_names() -> None:
    detail = IncidentDetail(
        incident_id=uuid4(),
        hosp=True,
        hos_did="ID",
        hos_n="مستشفى الجنوب",
        hosm_d=2,
        hosf_d=1,
    )

    section = serialize_category_section(detail, "hospital")

    assert section is not None
    assert section["hos_n"] == "مستشفى الجنوب"
    assert section["hos_m_d"] == 2
    assert section["hos_f_d"] == 1
    assert "hosd" not in section


def test_serialize_did_locked_when_gate_off() -> None:
    detail = IncidentDetail(
        incident_id=uuid4(),
        press=True,
        press_did="D",
        hc=False,
        hc_did="ID",
    )

    sections = serialize_incident_category_sections(detail)

    assert sections["press"] is not None
    assert sections["press"]["press_did"] == "D"
    assert sections["health_center"] is None


def test_serialize_school_damage_level_reads_db_column() -> None:
    detail = IncidentDetail(
        incident_id=uuid4(),
        school=True,
        school_damage_level="Partially Destroyed",
    )

    section = serialize_category_section(detail, "school_university")

    assert section is not None
    assert section["sch_damage_level"] == "Partially Destroyed"
