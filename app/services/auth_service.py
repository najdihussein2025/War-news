import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from passlib.context import CryptContext

from app.models.accounts import AuthSession, User
from app.repositories import AuthSessionRepository, UserRepository

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class InvalidCredentialsError(Exception):
    pass


def hash_access_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    def __init__(self, users: UserRepository, sessions: AuthSessionRepository) -> None:
        self.users = users
        self.sessions = sessions

    def login(self, username: str, password: str) -> tuple[User, str]:
        user = self.users.get_by_username(username.strip())
        if user is None or not user.is_active or not password_context.verify(password, user.password_hash):
            raise InvalidCredentialsError("Incorrect username or password.")

        user.last_login_at = datetime.now(timezone.utc)
        self.users.update(user)
        token = secrets.token_urlsafe(48)
        self.sessions.create(AuthSession(
            user_id=user.id,
            token_hash=hash_access_token(token),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
        ))
        return user, token

    def logout(self, token: str) -> None:
        session = self.sessions.get_active(hash_access_token(token))
        if session is not None:
            self.sessions.revoke(session)
