from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Columns copied 1:1 from ``incidents`` (everything except ``khabar_embedding``).
# The archive script builds its INSERT ... SELECT from this tuple, so a column
# added to ``incidents`` later is simply not archived until it is added here and
# in a migration.
ARCHIVE_INCIDENT_COLUMNS = (
    "id", "raw_message_id", "village_id", "village_display_name", "condition_id", "source_id",
    "event_month", "event_date", "event_time", "khabar", "story_group_id", "note", "moh",
    "martyrs", "worker_name", "source_link", "source_link_2", "total_deaths", "total_injuries",
    "casualty_status", "casualty_deaths_status", "casualty_injuries_status",
    "casualty_status_remaining_total", "quality_flags", "casualty_is_preliminary",
    "casualty_status_evidence", "deaths", "injuries", "injuries_extra", "note_extra",
    "note_extra_2", "exact_hash", "incident_key", "duplicate_flag", "duplicate_level",
    "duplicate_similarity_score", "details_pending", "is_deleted", "deleted_reason",
    "decision_reason", "decision_source_summary_id", "decision_ref_incident_id", "decided_at",
    "created_by", "created_at", "updated_at", "origin", "source_summary_item_id",
    "verification_status", "verification_reason", "verified_by_user_id", "verified_at", "version",
    "locked_by_user_id", "edit_lock_expires_at",
)
# Columns joined in from ``incident_details``.
ARCHIVE_DETAIL_COLUMNS = ("male_d", "male_i", "female_d", "female_i", "children_d", "children_i")


class IncidentArchive(Base):
    """Frozen snapshot of ``incidents`` taken before the data reset. No foreign keys."""

    __tablename__ = "incidents_archive"
    __table_args__ = (
        Index("ix_incidents_archive_event_date", "event_date"),
        Index("ix_incidents_archive_village_id", "village_id"),
        Index("ix_incidents_archive_condition_id", "condition_id"),
        Index("ix_incidents_archive_id", "id"),
    )

    archive_batch: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    archived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    raw_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    village_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    village_display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    condition_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    event_month: Mapped[str | None] = mapped_column(String, nullable=True)
    event_date: Mapped[date] = mapped_column(nullable=False)
    event_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    khabar: Mapped[str] = mapped_column(Text, nullable=False)
    story_group_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    moh: Mapped[str | None] = mapped_column(String, nullable=True)
    martyrs: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_name: Mapped[str | None] = mapped_column(String, nullable=True)
    source_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_link_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_deaths: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_injuries: Mapped[int | None] = mapped_column(Integer, nullable=True)
    casualty_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    casualty_deaths_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    casualty_injuries_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    casualty_status_remaining_total: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    quality_flags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    casualty_is_preliminary: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    casualty_status_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    deaths: Mapped[int | None] = mapped_column(Integer, nullable=True)
    injuries: Mapped[int | None] = mapped_column(Integer, nullable=True)
    injuries_extra: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note_extra: Mapped[str | None] = mapped_column(Text, nullable=True)
    note_extra_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    exact_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    incident_key: Mapped[str | None] = mapped_column(String, nullable=True)
    duplicate_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duplicate_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    duplicate_similarity_score: Mapped[float | None] = mapped_column(nullable=True)
    details_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_source_summary_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    decision_ref_incident_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    origin: Mapped[str | None] = mapped_column(String, nullable=True)
    source_summary_item_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False)
    verification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_by_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locked_by_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    edit_lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    male_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    male_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    female_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    female_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    children_d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    children_i: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bulletin_casualty_group_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    casualty_scope: Mapped[str | None] = mapped_column(String, nullable=True)
