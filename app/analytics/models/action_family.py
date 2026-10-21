from sqlalchemy import Boolean, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ActionFamily(Base):
    __tablename__ = "action_families"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String, nullable=False)
    name_ar: Mapped[str] = mapped_column(String, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_air_violation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    counts_in_headline: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class ConditionFamily(Base):
    __tablename__ = "condition_families"

    condition_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conditions.id", ondelete="CASCADE"), primary_key=True
    )
    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("action_families.id", ondelete="RESTRICT"), nullable=False
    )
