from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Enum as SqlEnum,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MessageStatus(str, Enum):
    pending = "pending"
    parsed = "parsed"
    duplicate = "duplicate"
    rejected = "rejected"
    error = "error"


class RawMessage(Base):
    __tablename__ = "raw_messages"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "external_message_id",
            name="uq_raw_messages_source_external_message",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    message_datetime: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    status: Mapped[MessageStatus] = mapped_column(
        SqlEnum(MessageStatus, name="message_status"),
        nullable=False,
        default=MessageStatus.pending,
        server_default=text("'pending'"),
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    source = relationship("Source", back_populates="raw_messages")
