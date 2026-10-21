from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.news.models.condition import Condition
    from app.news.models.raw_message import RawMessage
    from app.news.models.village import Village
    from app.sources.models.source import Source


class AirViolation(Base):
    """Air activity without casualty or damage details.

    ``condition_id`` is expected to reference condition 34 (spy balloon),
    35 (warplane), 36 (surveillance aircraft), or 38 (helicopter hovering).
    One row is stored per report; breaches are counted at read time by
    ``breach_counting_service``. ``window_id`` is legacy and no longer read.
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
    village_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("villages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    caza_en: Mapped[str | None] = mapped_column(String, nullable=True)
    caza_ar: Mapped[str | None] = mapped_column(String, nullable=True)
    event_month: Mapped[str | None] = mapped_column(String, nullable=True)
    war_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_date: Mapped[date] = mapped_column(nullable=False, index=True)
    event_time: Mapped[time | None] = mapped_column(nullable=True)
    window_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    review_status: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    khabar: Mapped[str] = mapped_column(Text, nullable=False)
    note_1: Mapped[str | None] = mapped_column(Text, nullable=True)
    note_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    edit_lock_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    __mapper_args__ = {"version_id_col": version}
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    raw_message: Mapped["RawMessage | None"] = relationship("RawMessage")
    condition: Mapped["Condition"] = relationship("Condition")
    source: Mapped["Source"] = relationship("Source")
    village: Mapped["Village | None"] = relationship("Village")
    locations: Mapped[list["AirViolationLocation"]] = relationship(
        "AirViolationLocation",
        cascade="all, delete-orphan",
        back_populates="air_violation",
    )


class AirViolationLocation(Base):
    __tablename__ = "air_violation_locations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    air_violation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("air_violations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    village_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("villages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    raw_location_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_span: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    air_violation: Mapped["AirViolation"] = relationship(
        "AirViolation",
        back_populates="locations",
    )
    village: Mapped["Village"] = relationship("Village")
