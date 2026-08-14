from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Village(Base):
    __tablename__ = "villages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    acs_code: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    acs_name: Mapped[str | None] = mapped_column(String, nullable=True)
    cad_name: Mapped[str | None] = mapped_column(String, nullable=True)
    ref_name_en: Mapped[str | None] = mapped_column(String, nullable=True)
    ref_name_ar: Mapped[str | None] = mapped_column(String, nullable=True)
    caza_en: Mapped[str | None] = mapped_column(String, nullable=True)
    caza_ar: Mapped[str | None] = mapped_column(String, nullable=True)
    mohafaza_en: Mapped[str | None] = mapped_column(String, nullable=True)
    mohafaza_ar: Mapped[str | None] = mapped_column(String, nullable=True)
    coord_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    coord_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
