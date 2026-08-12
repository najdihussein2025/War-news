from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Condition(Base):
    __tablename__ = "conditions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_en: Mapped[str] = mapped_column(String, nullable=False)
    action_ar: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
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
