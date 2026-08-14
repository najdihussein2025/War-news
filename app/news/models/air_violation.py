from datetime import date, datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.news.models.condition import Condition
    from app.news.models.raw_message import RawMessage
    from app.sources.models.source import Source


class AirViolation(Base):
    """Air activity without casualty or damage details.

    ``condition_id`` is expected to reference condition 35 (warplane),
    36 (surveillance aircraft), or 38 (helicopter hovering).
    """

    __tablename__ = "air_violations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    raw_message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("raw_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    condition_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("conditions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    caza_en: Mapped[str | None] = mapped_column(String, nullable=True)
    caza_ar: Mapped[str | None] = mapped_column(String, nullable=True)
    event_month: Mapped[str | None] = mapped_column(String, nullable=True)
    event_date: Mapped[date] = mapped_column(nullable=False, index=True)
    event_time: Mapped[time | None] = mapped_column(nullable=True)
    khabar: Mapped[str] = mapped_column(Text, nullable=False)
    note_1: Mapped[str | None] = mapped_column(Text, nullable=True)
    note_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    raw_message: Mapped["RawMessage | None"] = relationship("RawMessage")
    condition: Mapped["Condition"] = relationship("Condition")
    source: Mapped["Source"] = relationship("Source")
