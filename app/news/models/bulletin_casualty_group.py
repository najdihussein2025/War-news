from datetime import datetime
from enum import Enum

from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
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
        CheckConstraint(
            "total_overridden = false OR (total_override_reason IS NOT NULL AND total_override_at IS NOT NULL)",
            name="ck_bulletin_casualty_groups_override_has_reason",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    raw_message_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("raw_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Village ids in first-mention (text) order. Never sorted: the first entry
    # is the owner of a shared toll. See also BulletinCasualtyGroupMember.
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
    # Shared toll owner: the first village mentioned in the message text. The full
    # toll lives on this incident only; member incidents keep null casualties.
    owner_village_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("villages.id", ondelete="SET NULL"),
        nullable=True,
    )
    owner_incident_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Explicit admin override of the group total (the total otherwise stays
    # equal to the original shared toll when the admin distributes it).
    total_overridden: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    total_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_override_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    total_override_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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


class BulletinCasualtyGroupMember(Base):
    """One village of a shared-toll group, in first-mention order (ordinal 0 = owner)."""

    __tablename__ = "bulletin_casualty_group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "village_id", name="uq_bulletin_group_member_village"),
        UniqueConstraint("group_id", "ordinal", name="uq_bulletin_group_member_ordinal"),
        Index("ix_bulletin_group_members_incident", "incident_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bulletin_casualty_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    village_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("villages.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    incident_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="SET NULL"),
        nullable=True,
    )
