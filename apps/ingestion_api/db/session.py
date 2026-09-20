"""Engine/session factory. `DATABASE_URL` defaults to an in-memory SQLite
DB so Phase 1 unit tests need no running database; docker-compose and prod
set ``DATABASE_URL=mysql+pymysql://...`` (preferred) or Postgres."""

from __future__ import annotations

import os

from sqlalchemy.orm import Session, sessionmaker

from apps.ingestion_api.db.models import Base
from packages.db_engine import create_app_engine

DEFAULT_SQLITE_URL = "sqlite:///:memory:"

# Arbitrary fixed key for the schema-creation advisory lock. Only used to
# serialize `CREATE TABLE` across services that start concurrently.
_SCHEMA_LOCK_KEY = 727274


def make_engine(database_url: str | None = None):
    url = database_url or os.environ.get("DATABASE_URL", DEFAULT_SQLITE_URL)

    def _create_all(bind) -> None:
        Base.metadata.create_all(bind=bind)

    return create_app_engine(
        url,
        metadata_create_all=_create_all,
        schema_lock_key=_SCHEMA_LOCK_KEY,
    )


def make_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    engine = make_engine(database_url)
    return sessionmaker(bind=engine, expire_on_commit=False)
