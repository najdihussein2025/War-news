from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class VillageLocationAlias(Base):
    """Exact-match location alias that resolves to a canonical village.

    Used for city-level and neighborhood mentions that are not ACS villages
    themselves (e.g. مدينة النبطية, حي المسلخ) so fuzzy matching does not
    fall through to an unrelated nearby row.
    """

    __tablename__ = "village_location_aliases"
    __table_args__ = (
        UniqueConstraint("alias_normalized", name="uq_village_location_aliases_norm"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alias_text: Mapped[str] = mapped_column(String, nullable=False)
    alias_normalized: Mapped[str] = mapped_column(String, nullable=False)
    village_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("villages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    note: Mapped[str | None] = mapped_column(String, nullable=True)
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
