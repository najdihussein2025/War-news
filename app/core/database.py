from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

database_url = settings.database_url
dialect_name = make_url(database_url).get_backend_name()
engine_kwargs = {"echo": False}

if dialect_name == "postgresql":
    engine_kwargs.update(
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=20,
        max_overflow=10,
        connect_args={"application_name": settings.pg_application_name},
    )

engine = create_engine(database_url, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
