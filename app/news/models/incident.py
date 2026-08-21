from datetime import date, datetime, time
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.core.database import Base

if TYPE_CHECKING:
    from app.accounts.models.user import User
    from app.news.models.condition import Condition
    from app.news.models.duplicate_match import DuplicateMatch
    from app.news.models.incident_detail import IncidentDetail
    from app.news.models.incident_update import IncidentUpdate
    from app.news.models.raw_message import RawMessage
    from app.sources.models.source import Source
    from app.news.models.village import Village


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    raw_message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("raw_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    village_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("villages.id", ondelete="RESTRICT"),
        nullable=True,
    )
    condition_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("conditions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_month: Mapped[str | None] = mapped_column(String, nullable=True)
    event_date: Mapped[date] = mapped_column(nullable=False)
    event_time: Mapped[time | None] = mapped_column(nullable=True)
    khabar: Mapped[str] = mapped_column(Text, nullable=False)
    khabar_embedding: Mapped[list[float] | None] = mapped_column(
        Vector(384),
        nullable=True,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    moh: Mapped[str | None] = mapped_column(String, nullable=True)
    martyrs: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_name: Mapped[str | None] = mapped_column(String, nullable=True)
    source_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Meaning unconfirmed, preserve raw value.
    source_link_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_deaths: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_injuries: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deaths: Mapped[int | None] = mapped_column(Integer, nullable=True)
    injuries: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Meaning unconfirmed, preserve raw value.
    injuries_extra: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Meaning unconfirmed, preserve raw value.
    note_extra: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Meaning unconfirmed, preserve raw value.
    note_extra_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    exact_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    incident_key: Mapped[str | None] = mapped_column(String, nullable=True)
    duplicate_flag: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    details_pending: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    raw_message: Mapped["RawMessage | None"] = relationship("RawMessage")
    village: Mapped["Village | None"] = relationship("Village")
    condition: Mapped["Condition | None"] = relationship("Condition")
    source: Mapped["Source | None"] = relationship("Source")
    creator: Mapped["User | None"] = relationship("User", foreign_keys=[created_by])
    details: Mapped["IncidentDetail | None"] = relationship(
        "IncidentDetail",
        back_populates="incident",
        cascade="all, delete-orphan",
        uselist=False,
    )
    duplicate_matches: Mapped[list["DuplicateMatch"]] = relationship(
        "DuplicateMatch",
        back_populates="incident",
        cascade="all, delete-orphan",
        foreign_keys="DuplicateMatch.incident_id",
    )
    incident_updates: Mapped[list["IncidentUpdate"]] = relationship(
        "IncidentUpdate",
        back_populates="incident",
        cascade="all, delete-orphan",
    )
