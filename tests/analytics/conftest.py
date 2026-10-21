import pytest
from sqlalchemy.orm import Session

from tests.analytics.support import World, analytics_engine, clean_world, seed_reference


@pytest.fixture(scope="session")
def engine():
    eng = analytics_engine()
    seed_reference(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine):
    clean_world(engine)
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture()
def world(db) -> World:
    return World(db)
