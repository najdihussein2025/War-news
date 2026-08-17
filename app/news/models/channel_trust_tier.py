from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TrustTier(str, Enum):
    official = "official"
    trusted = "trusted"
    detail = "detail"


class ChannelTrustTier(Base):
    __tablename__ = "channel_trust_tiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    tier: Mapped[TrustTier] = mapped_column(
        SqlEnum(TrustTier, name="trust_tier"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
