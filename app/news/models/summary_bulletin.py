from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, Enum as SqlEnum, ForeignKey, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SummaryKind(str, Enum):
    full_day = "full_day"
    partial = "partial"
    unknown = "unknown"


class SummaryStatus(str, Enum):
    detected = "detected"
    parsed = "parsed"
    needs_review = "needs_review"
    awaiting_window = "awaiting_window"
    reconciling = "reconciling"
    reconciled = "reconciled"
    skipped_repost = "skipped_repost"
    failed = "failed"


class SummaryModifier(str, Enum):
    none = "none"
    outskirts = "outskirts"
    between = "between"


class SummaryItemOrigin(str, Enum):
    parser = "parser"
    llm_crosscheck = "llm_crosscheck"


class SummaryResolution(str, Enum):
    resolved = "resolved"
    unresolved_location = "unresolved_location"
    unknown_header = "unknown_header"


class SummaryReconciliationStatus(str, Enum):
    pending = "pending"
    matched = "matched"
    created = "created"
    ambiguous = "ambiguous"


class SummaryReviewStatus(str, Enum):
    open = "open"
    resolved = "resolved"
    dismissed = "dismissed"


class SummaryBulletin(Base):
    __tablename__ = "summary_bulletins"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    raw_message_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("raw_messages.id", ondelete="CASCADE"), unique=True, nullable=False)
    source_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("sources.id", ondelete="SET NULL"), nullable=True)
    channel: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[SummaryKind] = mapped_column(SqlEnum(SummaryKind, name="summary_kind"), nullable=False, default=SummaryKind.unknown)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    fingerprint: Mapped[str] = mapped_column(Text, index=True, nullable=False)
    canonical_summary_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("summary_bulletins.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[SummaryStatus] = mapped_column(SqlEnum(SummaryStatus, name="summary_status"), nullable=False, default=SummaryStatus.detected)
    process_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SummaryItem(Base):
    __tablename__ = "summary_items"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    summary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("summary_bulletins.id", ondelete="CASCADE"), index=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    header_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    condition_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("conditions.id", ondelete="SET NULL"), nullable=True)
    location_text: Mapped[str] = mapped_column(Text, nullable=False)
    primary_village_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("villages.id", ondelete="SET NULL"), nullable=True)
    secondary_village_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("villages.id", ondelete="SET NULL"), nullable=True)
    modifier: Mapped[SummaryModifier] = mapped_column(SqlEnum(SummaryModifier, name="summary_modifier"), nullable=False, default=SummaryModifier.none)
    reported_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_span: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[SummaryItemOrigin] = mapped_column(SqlEnum(SummaryItemOrigin, name="summary_item_origin"), nullable=False, default=SummaryItemOrigin.parser)
    resolution: Mapped[SummaryResolution] = mapped_column(SqlEnum(SummaryResolution, name="summary_resolution"), nullable=False, default=SummaryResolution.resolved)
    reconciliation_status: Mapped[SummaryReconciliationStatus] = mapped_column(SqlEnum(SummaryReconciliationStatus, name="summary_reconciliation_status"), nullable=False, default=SummaryReconciliationStatus.pending)
    matched_incident_id: Mapped[object | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True)
    created_incident_id: Mapped[object | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SummaryReviewTask(Base):
    __tablename__ = "summary_review_tasks"
    __table_args__ = (UniqueConstraint("summary_id", name="uq_summary_review_tasks_summary"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    summary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("summary_bulletins.id", ondelete="CASCADE"), nullable=False)
    reasons: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[SummaryReviewStatus] = mapped_column(SqlEnum(SummaryReviewStatus, name="summary_review_status"), nullable=False, default=SummaryReviewStatus.open)
    resolved_by: Mapped[object | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
