from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EmergencyOrganization(Base):
    """Controlled vocabulary for emergency-response organizations whose
    personnel / vehicles are referenced as affected in incident reports.

    Mirrors ``villages`` / ``conditions``: canonical name, English reference
    name, alias list for similarity matching, and a trigram index on
    ``name_ar``. Deliberately unrelated to ``incidents.moh`` — that field is
    Ministry of Health *confirmation of the incident*, this table answers
    *which emergency org was hit*.
    """

    __tablename__ = "emergency_organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name_ar: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String, nullable=False)
    # Alias phrasings (e.g. "سيارة إسعاف") scored via word_similarity() alongside
    # name_ar / name_en. Spacing variants are handled by compact normalization,
    # mirroring the villages matcher.
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default=list,
        server_default=text("'{}'::varchar[]"),
    )
    # Free-text tag for later filtering: civil_defense | health | scout_paramedic
    # | generic. Kept as a plain string (no enum) per the spec.
    org_type: Mapped[str | None] = mapped_column(String, nullable=True)
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
