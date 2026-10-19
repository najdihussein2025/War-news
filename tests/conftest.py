"""Root test configuration: abort the whole session on an unsafe database."""
from __future__ import annotations

import os

import pytest

from tests.db_guard import UnsafeTestDatabase, assert_safe_test_database


def pytest_sessionstart(session: pytest.Session) -> None:
    # Runs before collection, so it sees the environment as the user set it,
    # and before any fixture or test module can touch a database.
    try:
        env_url = os.environ.get("DATABASE_URL")
        if env_url:
            assert_safe_test_database(env_url, label="DATABASE_URL")
        from app.core.config import settings

        assert_safe_test_database(settings.database_url, label="effective settings.database_url")
    except UnsafeTestDatabase as exc:
        raise pytest.UsageError(f"ABORTING TEST SESSION: {exc}") from exc
