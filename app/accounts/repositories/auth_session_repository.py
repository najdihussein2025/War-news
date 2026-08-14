from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.accounts.models import AuthSession, User


class AuthSessionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, session: AuthSession) -> AuthSession:
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_active(self, token_hash: str) -> AuthSession | None:
        now = datetime.now(timezone.utc)
        return self.db.scalar(select(AuthSession).options(joinedload(AuthSession.user).joinedload(User.role)).where(
            AuthSession.token_hash == token_hash,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        ))

    def revoke(self, session: AuthSession) -> None:
        session.revoked_at = datetime.now(timezone.utc)
        self.db.commit()
