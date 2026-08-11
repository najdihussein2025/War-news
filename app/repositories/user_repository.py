from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.accounts import User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, user: User) -> User:
        self.db.add(user)
        self.db.flush()
        self.db.refresh(user)
        return user

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
        self.db.flush()
        self.db.refresh(user)
        return user

    def soft_deactivate(self, user: User) -> User:
        user.is_active = False
        return self.update(user)
