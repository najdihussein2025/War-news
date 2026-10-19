import pytest

from tests.db_guard import (
    UnsafeTestDatabase,
    assert_safe_test_database,
    assert_scratch_truncation_allowed,
)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg2://u:p@db:5432/war_news_dev",
        "postgresql+psycopg2://u:p@db:5432/war_news_devtest",
        "postgresql+psycopg2://u:p@db:5432/war_news",
        "postgresql+psycopg2://u:p@127.0.0.1:5434/war_news_dev",
        "postgresql+psycopg2://u:p@db:5432/",
    ],
)
def test_guard_rejects_non_test_database_names(url):
    with pytest.raises(UnsafeTestDatabase, match="_test"):
        assert_safe_test_database(url)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1"])
@pytest.mark.parametrize("port", [5432, 5433])
def test_guard_rejects_deployment_host_and_port_even_for_test_name(host, port):
    shown = f"[{host}]" if ":" in host else host
    with pytest.raises(UnsafeTestDatabase, match="deployment"):
        assert_safe_test_database(f"postgresql+psycopg2://u:p@{shown}:{port}/war_news_dev_test")


def test_guard_rejects_extra_protected_target(monkeypatch):
    monkeypatch.setenv("PROTECTED_DB_TARGETS", "prod-db:6000")
    with pytest.raises(UnsafeTestDatabase):
        assert_safe_test_database("postgresql+psycopg2://u:p@prod-db:6000/x_test")


def test_guard_accepts_dev_stack_database():
    assert_safe_test_database("postgresql+psycopg2://u:p@db:5432/war_news_dev_test")
    assert_safe_test_database("postgresql+psycopg2://u:p@127.0.0.1:5434/war_news_dev_test")
    assert_safe_test_database("sqlite+pysqlite:///:memory:")


def test_truncation_gate_requires_test_suffix():
    with pytest.raises(UnsafeTestDatabase):
        assert_scratch_truncation_allowed("postgresql+psycopg2://u:p@db:5432/war_news_dev")
    assert_scratch_truncation_allowed("postgresql+psycopg2://u:p@db:5432/war_news_dev_test")
