from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, DateTime, Enum as SqlEnum, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CasualtyScope(str, Enum):
    per_village_exact = "per_village_exact"
    bulletin_aggregate = "bulletin_aggregate"
    unspecified = "unspecified"


class BulletinBreakdownStatus(str, Enum):
    pending = "pending"
    resolved = "resolved"
    expired = "expired"
    n_a = "n_a"


class BulletinCasualtyGroup(Base):
    __tablename__ = "bulletin_casualty_groups"
    __table_args__ = (
        UniqueConstraint("raw_message_id", name="uq_bulletin_casualty_groups_raw_message"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    raw_message_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("raw_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    village_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False)
    casualty_scope: Mapped[CasualtyScope] = mapped_column(
        SqlEnum(CasualtyScope, name="casualty_scope"),
        nullable=False,
    )
    total_deaths: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_injuries: Mapped[int | None] = mapped_column(Integer, nullable=True)
    breakdown_status: Mapped[BulletinBreakdownStatus] = mapped_column(
        SqlEnum(BulletinBreakdownStatus, name="bulletin_breakdown_status"),
        nullable=False,
        default=BulletinBreakdownStatus.pending,
    )
    window_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolved_by_raw_message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("raw_messages.id", ondelete="SET NULL"),
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
