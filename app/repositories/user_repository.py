from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.accounts import Role, RoleName, User


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

    def soft_deactivate(self, user: User) -> User:
        user.is_active = False
        return self.update(user)

    def set_active(self, user: User, is_active: bool) -> User:
        user.is_active = is_active
        return self.update(user)

    def delete(self, user: User) -> None:
        self.db.delete(user)
        self.db.commit()
