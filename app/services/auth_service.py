import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from passlib.context import CryptContext

from app.models.accounts import AuthSession, User
from app.core.config import settings
from app.repositories import AuthSessionRepository, LoginThrottleRepository, UserRepository

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class InvalidCredentialsError(Exception):
    pass


class AccountInactiveError(Exception):
    pass


class LoginRateLimitError(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        minutes = max(1, (retry_after_seconds + 59) // 60)
        super().__init__(f"Too many failed login attempts. Try again in {minutes} minute(s).")


def hash_access_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    def __init__(self, users: UserRepository, sessions: AuthSessionRepository, throttles: LoginThrottleRepository) -> None:
        self.users = users
        self.sessions = sessions
        self.throttles = throttles

    def login(self, username: str, password: str, client_ip: str, device_id: str) -> tuple[User, str]:
        user = self.users.get_by_username(username.strip())
        now = datetime.now(timezone.utc)
        throttles = [
            self.throttles.get_or_create(f"ip:{client_ip}"),
            self.throttles.get_or_create(f"device:{hash_access_token(device_id)}"),
        ]

        for throttle in throttles:
            if throttle.locked_until is not None:
                if throttle.locked_until > now:
                    retry_after = max(1, int((throttle.locked_until - now).total_seconds()) + 1)
                    raise LoginRateLimitError(retry_after)
                throttle.failed_attempts = 0
                throttle.locked_until = None
                self.throttles.save(throttle)

        if user is not None and user.locked_until is not None:
            if user.locked_until > now:
                retry_after = max(1, int((user.locked_until - now).total_seconds()) + 1)
                raise LoginRateLimitError(retry_after)
            user.failed_login_attempts = 0
            user.locked_until = None
            self.users.update(user)

        if user is None or not password_context.verify(password, user.password_hash):
            source_locked = False
            for throttle in throttles:
                throttle.failed_attempts += 1
                if throttle.failed_attempts >= settings.login_max_failed_attempts:
                    throttle.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
                    source_locked = True
                self.throttles.save(throttle)

            if user is not None:
                user.failed_login_attempts += 1
                account_locked = user.failed_login_attempts >= settings.login_max_failed_attempts
                if account_locked:
                    user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
                self.users.update(user)
                if account_locked or source_locked:
                    raise LoginRateLimitError(settings.login_lockout_minutes * 60)
            elif source_locked:
                raise LoginRateLimitError(settings.login_lockout_minutes * 60)
            raise InvalidCredentialsError("Incorrect username or password.")
        if not user.is_active:
            raise AccountInactiveError("This account is deactivated.")

        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = now
        self.users.update(user)
        for throttle in throttles:
            throttle.failed_attempts = 0
            throttle.locked_until = None
            self.throttles.save(throttle)
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
