from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Watermark row written by scripts/live_sweep_new_only.py. Kept here so the
# live-sweep worker and read-only health checks reference one constant.
LIVE_SWEEP_NAME = "live_sweep_new_only"


class SweepCursor(Base):
    __tablename__ = "sweep_cursors"

    sweep_name: Mapped[str] = mapped_column(Text, primary_key=True)
    last_processed_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
