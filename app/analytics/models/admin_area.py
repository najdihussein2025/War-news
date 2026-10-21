from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Numeric, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

ADMIN_LEVELS = ("mohafaza", "caza", "village")


class AdminArea(Base):
    """One HDX/OCHA administrative area. ``code`` is the geojson ``properties.code``."""

    __tablename__ = "admin_areas"
    __table_args__ = (
        CheckConstraint("level IN ('mohafaza', 'caza', 'village')", name="ck_admin_areas_level"),
        Index("ix_admin_areas_level", "level"),
        Index("ix_admin_areas_caza_code", "caza_code"),
        Index("ix_admin_areas_mohafaza_code", "mohafaza_code"),
    )

    code: Mapped[str] = mapped_column(String, primary_key=True)
    level: Mapped[str] = mapped_column(String, nullable=False)
    name_en: Mapped[str | None] = mapped_column(String, nullable=True)
    name_ar: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_code: Mapped[str | None] = mapped_column(
        String, ForeignKey("admin_areas.code"), nullable=True
    )
    caza_code: Mapped[str | None] = mapped_column(String, nullable=True)
    mohafaza_code: Mapped[str | None] = mapped_column(String, nullable=True)
    area_km2: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    center_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    center_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_disputed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
