"""Refuse to run the test suite against anything but an isolated ``*_test`` database.

On 2026-10-19 the suite was run against the live ``war_news_dev`` database and
``tests/test_pipeline_jobs.py`` committed ``DELETE FROM pipeline_sweep_jobs``.
There is intentionally no override flag: to run the tests, point DATABASE_URL at
a database whose name ends in ``_test`` (the dev stack does this).
"""
from __future__ import annotations

import os

from sqlalchemy.engine import make_url

TEST_DATABASE_SUFFIX = "_test"

# host:port pairs that belong to the deployment stack or the native Windows
# PostgreSQL service (see RUNBOOK.md). Extra pairs can be ADDED with the
# PROTECTED_DB_TARGETS env var ("host:port,host:port"); none can be removed.
_LOOPBACK = ("localhost", "127.0.0.1", "::1", "host.docker.internal")
_DEFAULT_PROTECTED_PORTS = (5432, 5433)


class UnsafeTestDatabase(RuntimeError):
    pass


def _normalise_host(host: str | None) -> str:
    return (host or "localhost").strip().lower()


def protected_targets() -> set[tuple[str, int]]:
    targets = {(host, port) for host in _LOOPBACK for port in _DEFAULT_PROTECTED_PORTS}
    for item in os.environ.get("PROTECTED_DB_TARGETS", "").split(","):
        item = item.strip()
        if not item:
            continue
        host, _, port = item.rpartition(":")
        if host and port.isdigit():
            targets.add((_normalise_host(host), int(port)))
    return targets


def assert_safe_test_database(database_url: str, *, label: str = "DATABASE_URL") -> None:
    """Raise UnsafeTestDatabase unless ``database_url`` is an isolated test DB."""
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        return  # in-memory / file sqlite cannot reach a deployment database
    database = url.database or ""
    if not database.endswith(TEST_DATABASE_SUFFIX):
        raise UnsafeTestDatabase(
            f"{label} points at database {database!r}; the test suite only runs against "
            f"a database whose name ends in {TEST_DATABASE_SUFFIX!r}. Run the tests on "
            "the dev stack (see Docs/dev_stack.md). There is no override."
        )
    target = (_normalise_host(url.host), int(url.port or 5432))
    if target in protected_targets():
        raise UnsafeTestDatabase(
            f"{label} targets {target[0]}:{target[1]}, which is the deployment / native "
            "PostgreSQL address. Use the dev stack database port (see Docs/dev_stack.md)."
        )


def assert_scratch_truncation_allowed(database_url: str) -> None:
    """Extra gate for fixtures that TRUNCATE tables."""
    database = make_url(database_url).database or ""
    if not database.endswith(TEST_DATABASE_SUFFIX):
        raise UnsafeTestDatabase(
            f"refusing to TRUNCATE database {database!r}: name must end in {TEST_DATABASE_SUFFIX!r}"
        )
    assert_safe_test_database(database_url, label="SUMMARY_TEST_DATABASE_URL")
