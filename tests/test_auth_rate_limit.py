from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.accounts.services.auth_service import (
    AuthService,
    InvalidCredentialsError,
    LoginRateLimitError,
    password_context,
)


class FakeUsers:
    def __init__(self, user):
        self.user = user

    def get_by_username(self, username):
        return self.user if username == self.user.username else None

    def update(self, user):
        self.user = user
        return user


class FakeSessions:
    def __init__(self):
        self.created = []

    def create(self, session):
        self.created.append(session)
        return session


class FakeThrottles:
    def __init__(self):
        self.items = {}

    def get_or_create(self, client_ip):
        if client_ip not in self.items:
            self.items[client_ip] = SimpleNamespace(
                client_ip=client_ip,
                failed_attempts=0,
                locked_until=None,
            )
        return self.items[client_ip]

    def save(self, throttle):
        self.items[throttle.client_ip] = throttle
        return throttle


def make_service():
    user = SimpleNamespace(
        id="user-id",
        username="admin",
        password_hash=password_context.hash("correct-password"),
        is_active=True,
        failed_login_attempts=0,
        locked_until=None,
        last_login_at=None,
    )
    users = FakeUsers(user)
    return AuthService(users, FakeSessions(), FakeThrottles()), user


def test_third_failed_login_locks_account_for_five_minutes():
    service, user = make_service()

    with pytest.raises(InvalidCredentialsError):
        service.login("admin", "wrong-1", "192.0.2.1", "device-a")
    with pytest.raises(InvalidCredentialsError):
        service.login("admin", "wrong-2", "192.0.2.1", "device-a")
    with pytest.raises(LoginRateLimitError) as error:
        service.login("admin", "wrong-3", "192.0.2.1", "device-a")

    assert error.value.retry_after_seconds == 300
    assert user.failed_login_attempts == 3
    assert user.locked_until > datetime.now(timezone.utc) + timedelta(minutes=4)

    with pytest.raises(LoginRateLimitError):
        service.login("admin", "correct-password", "192.0.2.1", "device-a")


def test_successful_login_resets_failed_attempts():
    service, user = make_service()
    user.failed_login_attempts = 2

    logged_in_user, token = service.login("admin", "correct-password", "192.0.2.1", "device-a")

    assert logged_in_user is user
    assert token
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


def test_ip_lock_blocks_other_usernames():
    service, _ = make_service()

    with pytest.raises(InvalidCredentialsError):
        service.login("unknown-1", "wrong", "192.0.2.2", "device-b")
    with pytest.raises(InvalidCredentialsError):
        service.login("unknown-2", "wrong", "192.0.2.2", "device-b")
    with pytest.raises(LoginRateLimitError):
        service.login("unknown-3", "wrong", "192.0.2.2", "device-b")

    with pytest.raises(LoginRateLimitError):
        service.login("admin", "correct-password", "192.0.2.2", "device-b")


def test_device_lock_survives_ip_change():
    service, _ = make_service()

    with pytest.raises(InvalidCredentialsError):
        service.login("unknown-1", "wrong", "192.0.2.10", "device-c")
    with pytest.raises(InvalidCredentialsError):
        service.login("unknown-2", "wrong", "192.0.2.10", "device-c")
    with pytest.raises(LoginRateLimitError):
        service.login("unknown-3", "wrong", "192.0.2.10", "device-c")

    with pytest.raises(LoginRateLimitError):
        service.login("admin", "correct-password", "198.51.100.20", "device-c")
