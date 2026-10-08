"""Exercise every Alembic revision on a disposable PostgreSQL database."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import uuid

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.database import Base
import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.news.models  # noqa: F401
import app.sources.models  # noqa: F401

SUMMARY_MARKERS = ("summary_", "incident_origin", "source_summary_item_id")


def run_alembic(database_url: str, *args: str) -> None:
    subprocess.run(
        ["alembic", "-c", "alembic.ini", *args],
        check=True,
        env=os.environ | {"DATABASE_URL": database_url},
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True, help="Dev PostgreSQL URL; its database is not modified.")
    parser.add_argument("--name", default=f"war_news_migtest_{uuid.uuid4().hex[:8]}")
    args = parser.parse_args()
    base_url = make_url(args.database_url)
    test_url = base_url.set(database=args.name)
    admin = create_engine(base_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{args.name}"'))
        print(f"created {args.name}")
        target_url = test_url.render_as_string(hide_password=False)
        run_alembic(target_url, "upgrade", "head")
        run_alembic(target_url, "downgrade", "20261005_0075")
        run_alembic(target_url, "upgrade", "head")
        with create_engine(test_url).connect() as connection:
            diffs = compare_metadata(MigrationContext.configure(connection=connection), Base.metadata)
        summary_diffs = [diff for diff in diffs if any(marker in repr(diff) for marker in SUMMARY_MARKERS)]
        if summary_diffs:
            raise RuntimeError(f"Summary metadata/migration differences: {summary_diffs!r}")
        print("metadata check: no summary-table, enum, or incident provenance differences")
    finally:
        with admin.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :name AND pid <> pg_backend_pid()"), {"name": args.name})
            connection.execute(text(f'DROP DATABASE IF EXISTS "{args.name}"'))
        admin.dispose()
        print(f"dropped {args.name}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"migration round-trip failed: {exc}", file=sys.stderr)
        raise
