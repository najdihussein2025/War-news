from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.news.models.bulletin_casualty_group import (
    BulletinBreakdownStatus,
    BulletinCasualtyGroup,
    BulletinCasualtyGroupMember,
    CasualtyScope,
)
from app.news.models.incident import Incident


def ordered_unique(village_ids: list[int]) -> list[int]:
    """Deduplicate keeping first-mention order (never sorted)."""
    return list(dict.fromkeys(village_ids))


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
        owner_village_id: int | None = None,
    ) -> BulletinCasualtyGroup:
        """``village_ids`` must already be in text (first-mention) order.

        The owner of a shared toll is ``owner_village_id`` (default: the first
        village). Re-running for the same message yields the same owner.
        """
        now = created_at or datetime.now(timezone.utc)
        village_ids = ordered_unique(village_ids)
        if owner_village_id is None and village_ids:
            owner_village_id = village_ids[0]
        existing = self.get_by_raw_message_id(raw_message_id)
        if existing is not None:
            existing.village_ids = village_ids
            if not existing.total_overridden:
                existing.owner_village_id = owner_village_id
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
            self.sync_members(existing)
            return existing

        is_aggregate = casualty_scope == CasualtyScope.bulletin_aggregate
        group = BulletinCasualtyGroup(
            raw_message_id=raw_message_id,
            village_ids=village_ids,
            owner_village_id=owner_village_id,
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
        self.sync_members(group)
        return group

    def sync_members(self, group: BulletinCasualtyGroup) -> None:
        """Make the ordered member rows match ``group.village_ids`` (idempotent)."""
        wanted = [v for v in group.village_ids if isinstance(v, int) and not isinstance(v, bool)]
        current = {
            row.village_id: row
            for row in self.db.scalars(
                select(BulletinCasualtyGroupMember).where(
                    BulletinCasualtyGroupMember.group_id == group.id
                )
            ).all()
        }
        if [row.village_id for row in sorted(current.values(), key=lambda r: r.ordinal)] == wanted:
            return
        # Two-phase rewrite keeps the (group, ordinal) unique constraint satisfied.
        for row in current.values():
            self.db.delete(row)
        self.db.flush()
        incident_by_village = {
            row.village_id: row.incident_id for row in current.values() if row.incident_id
        }
        for ordinal, village_id in enumerate(wanted):
            self.db.add(
                BulletinCasualtyGroupMember(
                    group_id=group.id,
                    village_id=village_id,
                    ordinal=ordinal,
                    incident_id=incident_by_village.get(village_id),
                )
            )
        self.db.flush()

    def link_incidents(
        self,
        group: BulletinCasualtyGroup,
        incidents: list[Incident],
    ) -> None:
        """Attach each materialized incident to its member row; set the owner incident."""
        by_village = {
            incident.village_id: incident
            for incident in incidents
            if incident.village_id is not None and not getattr(incident, "is_deleted", False)
        }
        for member in self.db.scalars(
            select(BulletinCasualtyGroupMember).where(
                BulletinCasualtyGroupMember.group_id == group.id
            )
        ).all():
            incident = by_village.get(member.village_id)
            if incident is not None and member.incident_id != incident.id:
                member.incident_id = incident.id
                self.db.add(member)
            if incident is not None and member.village_id == group.owner_village_id:
                group.owner_incident_id = incident.id
                self.db.add(group)
        self.db.flush()

    def get_by_incident_id(self, incident_id) -> BulletinCasualtyGroup | None:
        return self.db.scalar(
            select(BulletinCasualtyGroup)
            .join(
                BulletinCasualtyGroupMember,
                BulletinCasualtyGroupMember.group_id == BulletinCasualtyGroup.id,
            )
            .where(BulletinCasualtyGroupMember.incident_id == incident_id)
        )

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
