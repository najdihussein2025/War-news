from uuid import UUID
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete as sa_delete, select, update as sa_update
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.orm.exc import StaleDataError

from app.accounts.models import Role, RoleName, User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, user: User) -> User:
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def exists(self) -> bool:
        return self.db.scalar(select(User.id).limit(1)) is not None

    def get_active_super_admin(self) -> User | None:
        return self.db.scalar(
            select(User)
            .join(Role, User.role_id == Role.id)
            .options(joinedload(User.role))
            .where(User.is_active.is_(True), Role.name == RoleName.super_admin)
            .order_by(User.created_at)
            .limit(1)
        )

    def get_by_id(self, user_id: UUID) -> User | None:
        return self.db.scalar(
            select(User).options(joinedload(User.role)).where(User.id == user_id)
        )

    def get_by_username(self, username: str) -> User | None:
        return self.db.scalar(
            select(User).options(joinedload(User.role)).where(User.username == username)
        )

    def list_all(self, offset: int = 0, limit: int = 50) -> list[User]:
        return list(
            self.db.scalars(
                select(User)
                .options(joinedload(User.role))
                .order_by(User.created_at.desc())
                .offset(offset)
                .limit(limit)
            ).all()
        )

    def update(self, user: User) -> User:
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def change_password(self, user_id: UUID, version: int, password_hash: str) -> User | None:
        result = self.db.execute(
            sa_update(User)
            .where(User.id == user_id, User.version == version)
            .values(password_hash=password_hash, version=User.version + 1)
        )
        if result.rowcount == 0:
            self.db.rollback()
            if self.db.get(User, user_id) is None:
                return None
            raise StaleDataError("Account version is stale.")
        self.db.commit()
        return self.get_by_id(user_id)

    def soft_deactivate(self, user: User) -> User:
        user.is_active = False
        return self.update(user)

    def set_active(self, user: User, is_active: bool) -> User:
        user.is_active = is_active
        return self.update(user)

    def delete(self, user: User) -> None:
        self.db.delete(user)
        self.db.commit()

    def update_by_admin(self, user_id: UUID, version: int, user_id_actor: UUID, values: dict) -> User | None:
        result = self.db.execute(
            sa_update(User)
            .where(
                User.id == user_id,
                User.version == version,
                User.admin_edit_locked_by_user_id == user_id_actor,
            )
            .values(
                **values,
                version=User.version + 1,
                admin_edit_locked_by_user_id=None,
                admin_edit_lock_expires_at=None,
            )
        )
        if result.rowcount == 0:
            self.db.rollback()
            if self.db.get(User, user_id) is None:
                return None
            raise StaleDataError("Account version is stale or its edit lock is not owned by this administrator.")
        self.db.commit()
        return self.get_by_id(user_id)

    def delete_by_admin(self, user_id: UUID, version: int, user_id_actor: UUID) -> bool:
        result = self.db.execute(
            sa_delete(User).where(
                User.id == user_id,
                User.version == version,
                User.admin_edit_locked_by_user_id == user_id_actor,
            )
        )
        if result.rowcount == 0:
            self.db.rollback()
            if self.db.get(User, user_id) is None:
                return False
            raise StaleDataError("Account version is stale or its edit lock is not owned by this administrator.")
        self.db.commit()
        return True

    def acquire_edit_lock(self, user_id: UUID, actor_id: UUID) -> User | None:
        now = datetime.now(timezone.utc)
        result = self.db.execute(
            sa_update(User)
            .where(
                User.id == user_id,
                (
                    User.admin_edit_locked_by_user_id.is_(None)
                    | (User.admin_edit_lock_expires_at <= now)
                    | (User.admin_edit_locked_by_user_id == actor_id)
                ),
            )
            .values(
                admin_edit_locked_by_user_id=actor_id,
                admin_edit_lock_expires_at=now + timedelta(minutes=5),
            )
        )
        if result.rowcount == 0:
            self.db.rollback()
            if self.db.get(User, user_id) is None:
                return None
            raise StaleDataError("Account is being edited by another super administrator.")
        self.db.commit()
        return self.get_by_id(user_id)

    def release_edit_lock(self, user_id: UUID, actor_id: UUID) -> bool:
        result = self.db.execute(
            sa_update(User)
            .where(User.id == user_id, User.admin_edit_locked_by_user_id == actor_id)
            .values(admin_edit_locked_by_user_id=None, admin_edit_lock_expires_at=None)
        )
        self.db.commit()
        return result.rowcount > 0
