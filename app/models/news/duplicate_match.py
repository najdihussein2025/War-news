from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum as SqlEnum, Float, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.accounts.user import User
    from app.models.news.incident import Incident


class MatchType(str, Enum):
    exact = "exact"
    soft = "soft"


class MatchStatus(str, Enum):
    pending = "pending"
    confirmed_duplicate = "confirmed_duplicate"
    false_positive = "false_positive"


class DuplicateMatch(Base):
    __tablename__ = "duplicate_matches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    matched_incident_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    match_type: Mapped[MatchType] = mapped_column(
        SqlEnum(MatchType, name="match_type"),
        nullable=False,
    )
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[MatchStatus] = mapped_column(
        SqlEnum(MatchStatus, name="match_status"),
        nullable=False,
        default=MatchStatus.pending,
        server_default=text("'pending'"),
    )
    resolved_by: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    incident: Mapped["Incident"] = relationship(
        "Incident",
        back_populates="duplicate_matches",
        foreign_keys=[incident_id],
    )
    matched_incident: Mapped["Incident"] = relationship(
        "Incident",
        foreign_keys=[matched_incident_id],
    )
    resolver: Mapped["User | None"] = relationship("User", foreign_keys=[resolved_by])
