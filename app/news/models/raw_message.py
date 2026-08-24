from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Boolean,
    Enum as SqlEnum,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.core.database import Base


class MessageStatus(str, Enum):
    pending = "pending"
    parsed = "parsed"
    duplicate = "duplicate"
    rejected = "rejected"
    error = "error"
    routed_air_violation = "routed_air_violation"


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
    source_platform: Mapped[str | None] = mapped_column(
        String,
        index=True,
        nullable=True,
    )
    source_name: Mapped[str | None] = mapped_column(
        String,
        index=True,
        nullable=True,
    )
    source_platform_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("source_platform.id", ondelete="SET NULL"),
        nullable=True,
    )
    origin_platform: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin_account: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    cnrs_classification: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    filter_result: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    low_confidence_relevance: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    extraction_result: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    match_result: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    content_embedding: Mapped[list[float] | None] = mapped_column(
        Vector(384),
        nullable=True,
    )
    duplicate_of_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("raw_messages.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
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
    extraction_retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    source = relationship("Source", back_populates="raw_messages")
    source_platform_ref = relationship("SourcePlatform", back_populates="raw_messages")
    duplicate_of: Mapped["RawMessage | None"] = relationship(
        "RawMessage",
        remote_side=[id],
        foreign_keys=[duplicate_of_id],
    )
