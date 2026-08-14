from datetime import datetime
from enum import Enum
from typing import Any, TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum as SqlEnum, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.accounts.models.user import User
    from app.news.models.incident import Incident


class UpdateAction(str, Enum):
    create = "create"
    edit = "edit"
    status_change = "status_change"
    delete = "delete"
    undo = "undo"


class IncidentUpdate(Base):
    __tablename__ = "incident_updates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    action: Mapped[UpdateAction] = mapped_column(
        SqlEnum(UpdateAction, name="update_action"),
        nullable=False,
    )
    old_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    new_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    performed_by: Mapped[str | None] = mapped_column(
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
        back_populates="incident_updates",
    )
    performer: Mapped["User | None"] = relationship("User", foreign_keys=[performed_by])
