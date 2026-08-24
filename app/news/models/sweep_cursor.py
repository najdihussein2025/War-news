from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


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
