"""5.2: default secrets are flagged; the seed no longer resets passwords."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.core.config import insecure_default_settings

import app.accounts.models  # noqa: F401,E402  (register all mappers before select(User))
import app.logs.models  # noqa: F401,E402
import app.news.models  # noqa: F401,E402
import app.sources.models  # noqa: F401,E402


def test_shipped_defaults_are_reported() -> None:
    current = SimpleNamespace(
        auth_secret_key="development-only-change-me",
        super_admin_seed_password="password",
    )
    assert insecure_default_settings(current) == [
        "auth_secret_key",
        "super_admin_seed_password",
    ]


def test_configured_secrets_are_not_reported() -> None:
    current = SimpleNamespace(auth_secret_key="x" * 40, super_admin_seed_password="s3cret!")
    assert insecure_default_settings(current) == []


def _seed_existing(monkeypatch, *, reset: str | None):
    from app.core.seeds import seed_super_admin as seed

    existing = SimpleNamespace(
        username="superadmin",
        password_hash="EXISTING",
        full_name="x",
        role_id=None,
        is_active=True,
        created_by_id=None,
    )
    db = MagicMock()
    db.scalar.return_value = existing
    monkeypatch.setattr(seed, "_ensure_roles", lambda db: {seed.RoleName.super_admin: SimpleNamespace(id=1)})
    if reset is None:
        monkeypatch.delenv("SUPER_ADMIN_SEED_RESET_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("SUPER_ADMIN_SEED_RESET_PASSWORD", reset)
    user, inserted = seed.seed_super_admin(db)
    return user, inserted


def test_seed_rerun_keeps_existing_password(monkeypatch) -> None:
    user, inserted = _seed_existing(monkeypatch, reset=None)

    assert inserted is False
    assert user.password_hash == "EXISTING"


def test_seed_reset_requires_explicit_opt_in(monkeypatch) -> None:
    user, _ = _seed_existing(monkeypatch, reset="1")

    assert user.password_hash != "EXISTING"
