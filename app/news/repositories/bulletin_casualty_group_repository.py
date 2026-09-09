from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.news.models.bulletin_casualty_group import (
    BulletinBreakdownStatus,
    BulletinCasualtyGroup,
    CasualtyScope,
)


class BulletinCasualtyGroupRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_for_message(
        self,
        *,
        raw_message_id: int,
        village_ids: list[int],
        casualty_scope: CasualtyScope,
        total_deaths: int | None,
        total_injuries: int | None,
        created_at: datetime | None = None,
    ) -> BulletinCasualtyGroup:
        now = created_at or datetime.now(timezone.utc)
        existing = self.get_by_raw_message_id(raw_message_id)
        if existing is not None:
            existing.village_ids = sorted(set(village_ids))
            existing.casualty_scope = casualty_scope
            if total_deaths is not None:
                existing.total_deaths = total_deaths
            if total_injuries is not None:
                existing.total_injuries = total_injuries
            if (
                casualty_scope == CasualtyScope.bulletin_aggregate
                and existing.breakdown_status == BulletinBreakdownStatus.n_a
            ):
                existing.breakdown_status = BulletinBreakdownStatus.pending
                existing.window_expires_at = now + timedelta(
                    hours=settings.bulletin_reconciliation_window_hours
                )
            existing.updated_at = now
            self.db.add(existing)
            self.db.flush()
            return existing

        is_aggregate = casualty_scope == CasualtyScope.bulletin_aggregate
        group = BulletinCasualtyGroup(
            raw_message_id=raw_message_id,
            village_ids=sorted(set(village_ids)),
            casualty_scope=casualty_scope,
            total_deaths=total_deaths,
            total_injuries=total_injuries,
            breakdown_status=(
                BulletinBreakdownStatus.pending
                if is_aggregate
                else BulletinBreakdownStatus.n_a
            ),
            window_expires_at=(
                now + timedelta(hours=settings.bulletin_reconciliation_window_hours)
                if is_aggregate
                else None
            ),
            created_at=now,
            updated_at=now,
        )
        self.db.add(group)
        self.db.flush()
        return group

    def get_by_raw_message_id(
        self,
        raw_message_id: int,
    ) -> BulletinCasualtyGroup | None:
        return self.db.scalar(
            select(BulletinCasualtyGroup).where(
                BulletinCasualtyGroup.raw_message_id == raw_message_id
            )
        )

    def list_open_groups(self, as_of: datetime) -> list[BulletinCasualtyGroup]:
        return list(
            self.db.scalars(
                select(BulletinCasualtyGroup)
                .where(
                    BulletinCasualtyGroup.breakdown_status
                    == BulletinBreakdownStatus.pending,
                    BulletinCasualtyGroup.window_expires_at > as_of,
                )
                .order_by(BulletinCasualtyGroup.id.asc())
            ).all()
        )

    def list_expiring_groups(self, as_of: datetime) -> list[BulletinCasualtyGroup]:
        return list(
            self.db.scalars(
                select(BulletinCasualtyGroup)
                .where(
                    BulletinCasualtyGroup.breakdown_status
                    == BulletinBreakdownStatus.pending,
                    BulletinCasualtyGroup.window_expires_at <= as_of,
                )
                .order_by(BulletinCasualtyGroup.id.asc())
            ).all()
        )

    def mark_resolved(
        self,
        group: BulletinCasualtyGroup,
        *,
        resolved_at: datetime,
        resolved_by_raw_message_id: int,
    ) -> None:
        group.breakdown_status = BulletinBreakdownStatus.resolved
        group.resolved_at = resolved_at
        group.resolved_by_raw_message_id = resolved_by_raw_message_id
        group.updated_at = resolved_at
        self.db.add(group)

    def mark_expired(
        self,
        group: BulletinCasualtyGroup,
        *,
        expired_at: datetime,
    ) -> None:
        group.breakdown_status = BulletinBreakdownStatus.expired
        group.updated_at = expired_at
        self.db.add(group)
