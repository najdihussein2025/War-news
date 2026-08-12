from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, Enum as SqlEnum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.news.incident import Incident


class DidValue(str, Enum):
    D = "D"
    ID = "ID"


# DID convention: for every *_did field paired with a controlling flag
# (for example, la + la_did), the _did value should be null when the flag is
# false/null and "D" or "ID" when the flag is true. This is enforced later at
# the application layer, not by a database constraint in this migration.
class IncidentDetail(Base):
    __tablename__ = "incident_details"

    incident_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        primary_key=True,
    )

    male_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    male_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    female_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    female_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    children_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    children_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    obs_duties: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    isf_gs: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    fire: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    arrested: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    lib_y_n: Mapped[str | None] = mapped_column(String, nullable=True)

    la: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    la_did: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    la_bldg: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    la_v: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    lam_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lam_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    laf_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    laf_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    la_td: Mapped[int | None] = mapped_column(Integer, nullable=True)
    la_ti: Mapped[int | None] = mapped_column(Integer, nullable=True)

    unifil: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    un_did: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    un_bldg: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    un_v: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    unm_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unm_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unf_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unf_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    un_td: Mapped[int | None] = mapped_column(Integer, nullable=True)
    un_ti: Mapped[int | None] = mapped_column(Integer, nullable=True)

    muni: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    muni_did: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    muni_bldg: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    muni_empl: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    munim_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    munim_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    munif_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    munif_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    muni_td: Mapped[int | None] = mapped_column(Integer, nullable=True)
    muni_ti: Mapped[int | None] = mapped_column(Integer, nullable=True)

    school: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    sch_did: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    school_name: Mapped[str | None] = mapped_column(String, nullable=True)
    school_damage_level: Mapped[str | None] = mapped_column(String, nullable=True)
    uni: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    uni_did: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    uni_name: Mapped[str | None] = mapped_column(String, nullable=True)

    church: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    chu_did: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    chu_n: Mapped[str | None] = mapped_column(String, nullable=True)
    mosque: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    mos_did: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    mosque_n: Mapped[str | None] = mapped_column(String, nullable=True)
    ceme: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ceme_did: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    ceme_n: Mapped[str | None] = mapped_column(String, nullable=True)
    releg: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    releg_did: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    releg_n: Mapped[str | None] = mapped_column(String, nullable=True)
    archeo: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    arch_did: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    arch_n: Mapped[str | None] = mapped_column(String, nullable=True)

    hosp: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    hos_did: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    hos_status: Mapped[str | None] = mapped_column(String, nullable=True)
    hos_n: Mapped[str | None] = mapped_column(String, nullable=True)
    hos_damage_level: Mapped[str | None] = mapped_column(String, nullable=True)
    nbr_evap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hosm_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hosm_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hosf_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hosf_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hosd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hosi: Mapped[int | None] = mapped_column(Integer, nullable=True)

    hc: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    hc_rela: Mapped[str | None] = mapped_column(String, nullable=True)
    hc_did: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    hc_damage_level: Mapped[str | None] = mapped_column(String, nullable=True)
    hcm_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hcm_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hcf_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hcf_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hcd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hci: Mapped[int | None] = mapped_column(Integer, nullable=True)

    emer: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    e_cars: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    car_nbr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    emer_rela: Mapped[str | None] = mapped_column(String, nullable=True)
    emer_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    emer_i: Mapped[int | None] = mapped_column(Integer, nullable=True)

    press: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    channel: Mapped[str | None] = mapped_column(String, nullable=True)
    press_did: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    pressm_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pressm_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pressf_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pressf_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pressd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pressi: Mapped[int | None] = mapped_column(Integer, nullable=True)

    gov: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gov_bui: Mapped[str | None] = mapped_column(String, nullable=True)
    gov_n: Mapped[str | None] = mapped_column(String, nullable=True)
    gb_did: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    gbm_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gbm_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gbf_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gbf_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gbd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gbi: Mapped[int | None] = mapped_column(Integer, nullable=True)

    road: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    road_d_id: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    road_blocked: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    road_name: Mapped[str | None] = mapped_column(String, nullable=True)
    bridge: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    bridge_blocked: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    bridge_name: Mapped[str | None] = mapped_column(String, nullable=True)

    car: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    card: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cari: Mapped[int | None] = mapped_column(Integer, nullable=True)
    carm_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    carm_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    carf_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    carf_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    carc_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    carc_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    moto: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    moto_did: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    moto_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    moto_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    con_veh: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    con_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    con_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    excavator: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    bulldozer: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    camion: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    bobcat: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    tracteur: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    total_con: Mapped[int | None] = mapped_column(Integer, nullable=True)

    crossing: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    litani: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    zahrani: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    drone_f: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    water: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    water_did: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    water_type: Mapped[str | None] = mapped_column(String, nullable=True)
    electric: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    electric_did: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    electric_type: Mapped[str | None] = mapped_column(String, nullable=True)
    olives_trees_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Purpose TBD, preserve raw value, do not build logic on this field yet.
    mjnoub: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    mj_did: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    other: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    other_did: Mapped[DidValue | None] = mapped_column(
        SqlEnum(DidValue, name="did_value"),
        nullable=True,
    )
    other_type: Mapped[str | None] = mapped_column(String, nullable=True)
    other_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    other_i: Mapped[int | None] = mapped_column(Integer, nullable=True)

    no_warning: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    warning: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Flag preserved from source data, labeling TBD, do not surface in UI without confirmation.
    genocide: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    building: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    apart: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    incident: Mapped["Incident"] = relationship("Incident", back_populates="details")
