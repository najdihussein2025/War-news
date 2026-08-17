from sqlalchemy import select
from sqlalchemy.orm import Session

from app.news.models import ChannelTrustTier


class ChannelTrustTierRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_tier_by_channel_name(
        self,
        channel_name: str,
    ) -> ChannelTrustTier | None:
        return self.db.scalar(
            select(ChannelTrustTier).where(
                ChannelTrustTier.channel_name == channel_name,
            )
        )

    def list_all(self) -> list[ChannelTrustTier]:
        return list(
            self.db.scalars(
                select(ChannelTrustTier).order_by(ChannelTrustTier.id.asc())
            ).all()
        )
