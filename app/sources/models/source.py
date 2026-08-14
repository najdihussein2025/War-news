from enum import Enum
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Enum as SqlEnum, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SourceType(str, Enum):
    telegram = "telegram"
    twitter = "twitter"
    facebook = "facebook"
    website = "website"
    api = "api"
    manual = "manual"
    other = "other"


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[SourceType] = mapped_column(
        SqlEnum(SourceType, name="source_type"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    last_cursor: Mapped[str | None] = mapped_column(String, nullable=True)
    auth_secret_ref: Mapped[str | None] = mapped_column(String, nullable=True)
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

    raw_messages = relationship(
        "RawMessage",
        back_populates="source",
        cascade="all, delete-orphan",
    )
    ingestion_logs = relationship(
        "IngestionLog",
        back_populates="source",
        cascade="all, delete-orphan",
    )
