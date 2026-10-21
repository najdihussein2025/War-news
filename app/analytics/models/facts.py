from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

BUCKET_COUNTED = "counted"
BUCKET_PENDING = "pending"
SOURCE_LIVE = "live"
SOURCE_ARCHIVE = "archive"


class AnalyticsIncidentFact(Base):
    """Daily incident aggregate per village x condition x bucket x source."""

    __tablename__ = "analytics_incident_facts"
    __table_args__ = (
        CheckConstraint("bucket IN ('counted', 'pending')", name="ck_analytics_incident_facts_bucket"),
        CheckConstraint("source IN ('live', 'archive')", name="ck_analytics_incident_facts_source"),
        UniqueConstraint(
            "event_date", "village_id", "condition_id", "bucket", "source",
            name="uq_analytics_incident_facts_grain",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_analytics_incident_facts_date", "event_date"),
        Index("ix_analytics_incident_facts_moh_date", "mohafaza_code", "event_date"),
        Index("ix_analytics_incident_facts_caza_date", "caza_code", "event_date"),
        Index("ix_analytics_incident_facts_village_date", "admin_village_code", "event_date"),
        Index("ix_analytics_incident_facts_family_date", "family_id", "event_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    admin_village_code: Mapped[str | None] = mapped_column(String, nullable=True)
    caza_code: Mapped[str | None] = mapped_column(String, nullable=True)
    mohafaza_code: Mapped[str | None] = mapped_column(String, nullable=True)
    village_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    condition_id: Mapped[int] = mapped_column(Integer, nullable=False)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False)
    bucket: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    archive_batch: Mapped[str | None] = mapped_column(String, nullable=True)
    incidents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deaths_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deaths_male: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deaths_female: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deaths_children: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deaths_unspecified: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    injuries_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    injuries_male: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    injuries_female: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    injuries_children: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    injuries_unspecified: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    aggregate_only_incidents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AnalyticsAirBreachFact(Base):
    """Daily air-violation breach aggregate per condition x counting unit."""

    __tablename__ = "analytics_air_breach_facts"
    __table_args__ = (
        CheckConstraint(
            "unit_level IN ('mohafaza', 'caza', 'village', 'unknown')",
            name="ck_analytics_air_breach_facts_level",
        ),
        UniqueConstraint(
            "breach_date", "condition_id", "unit_level", "area_code",
            name="uq_analytics_air_breach_facts_grain",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_analytics_air_breach_facts_date", "breach_date"),
        Index("ix_analytics_air_breach_facts_unit", "unit_level", "area_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    breach_date: Mapped[date] = mapped_column(Date, nullable=False)
    condition_id: Mapped[int] = mapped_column(Integer, nullable=False)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_level: Mapped[str] = mapped_column(String, nullable=False)
    area_code: Mapped[str | None] = mapped_column(String, nullable=True)
    mohafaza_code: Mapped[str | None] = mapped_column(String, nullable=True)
    caza_code: Mapped[str | None] = mapped_column(String, nullable=True)
    breaches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reports: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    needs_review_breaches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AnalyticsDirtyDate(Base):
    __tablename__ = "analytics_dirty_dates"
    __table_args__ = (
        CheckConstraint("kind IN ('incident', 'air')", name="ck_analytics_dirty_dates_kind"),
    )

    kind: Mapped[str] = mapped_column(String, primary_key=True)
    event_date: Mapped[date] = mapped_column(Date, primary_key=True)
    marked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
