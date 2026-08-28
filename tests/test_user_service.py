from types import SimpleNamespace
from uuid import uuid4

from app.accounts.models import RoleName
from app.accounts.services.user_service import UserConflictError, UserService, password_context
from sqlalchemy.orm.exc import StaleDataError


class FakeRoles:
    def get_by_id(self, _role_id):
        return None


class FakeUsers:
    def __init__(self, users):
        self.users = users
        self.updated = []

    def get_by_id(self, user_id):
        return self.users.get(user_id)

    def get_by_username(self, username):
        for user in self.users.values():
            if user.username == username:
                return user
        return None

    def change_password(self, user_id, version, password_hash):
        user = self.users[user_id]
        if user.version != version:
            raise StaleDataError("stale")
        user.password_hash = password_hash
        user.version += 1
        self.updated.append(user.id)
        return user


class FakeSessions:
    def __init__(self):
        self.revoked_user_ids = []

    def revoke_all_for_user(self, user_id):
        self.revoked_user_ids.append(user_id)
        return 2


def make_user(*, user_id, username, password, role_name):
    return SimpleNamespace(
        id=user_id,
        username=username,
        password_hash=password_context.hash(password),
        role=SimpleNamespace(name=role_name),
        version=1,
    )


def test_change_password_revokes_all_sessions_for_self_service():
    user_id = uuid4()
    user = make_user(
        user_id=user_id,
        username="admin",
        password="old-password",
        role_name=RoleName.admin,
    )
    users = FakeUsers({user_id: user})
    sessions = FakeSessions()
    service = UserService(FakeRoles(), users, sessions)

    service.change_password(user_id, "old-password", "new-password-123", 1, user)

    assert sessions.revoked_user_ids == [user_id]
    assert password_context.verify("new-password-123", user.password_hash)


def test_change_password_revokes_all_sessions_for_super_admin_override():
    target_id = uuid4()
    actor_id = uuid4()
    target_user = make_user(
        user_id=target_id,
        username="admin",
        password="old-password",
        role_name=RoleName.admin,
    )
    super_admin = make_user(
        user_id=actor_id,
        username="super",
        password="actor-password",
        role_name=RoleName.super_admin,
    )
    users = FakeUsers({target_id: target_user, actor_id: super_admin})
    sessions = FakeSessions()
    service = UserService(FakeRoles(), users, sessions)

    service.change_password(target_id, "actor-password", "new-password-123", 1, super_admin)

    assert sessions.revoked_user_ids == [target_id]
    assert password_context.verify("new-password-123", target_user.password_hash)


def test_change_password_rejects_a_stale_settings_version():
    user_id = uuid4()
    user = make_user(
        user_id=user_id,
        username="admin",
        password="old-password",
        role_name=RoleName.admin,
    )
    user.version = 2
    sessions = FakeSessions()
    service = UserService(FakeRoles(), FakeUsers({user_id: user}), sessions)

    try:
        service.change_password(user_id, "old-password", "new-password-123", 1, user)
    except UserConflictError as exc:
        assert "Refresh and try again" in str(exc)
    else:
        raise AssertionError("Expected a stale password change to be rejected")

    assert sessions.revoked_user_ids == []
    assert password_context.verify("old-password", user.password_hash)
