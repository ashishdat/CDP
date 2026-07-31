"""Engine/session factory. `DATABASE_URL` defaults to an in-memory SQLite
DB so Phase 1 unit tests need no running Postgres; docker-compose and prod
set `DATABASE_URL=postgresql+psycopg://...`."""

from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.ingestion_api.db.models import Base

DEFAULT_SQLITE_URL = "sqlite:///:memory:"

# Arbitrary fixed key for the schema-creation advisory lock. Only used to
# serialize `CREATE TABLE` across services that start concurrently (e.g.
# ingestion-api and document-preparation-worker both booting against a
# fresh Postgres in docker-compose) -- `create_all`'s own "does this table
# exist" check is not atomic, so two processes racing on a cold DB can both
# decide to create the same table and one gets a duplicate-key error on
# Postgres' internal pg_type catalog. Real migrations (Alembic, run once,
# out of band) replace this for anything beyond local dev.
_SCHEMA_LOCK_KEY = 727274


def make_engine(database_url: str | None = None):
    url = database_url or os.environ.get("DATABASE_URL", DEFAULT_SQLITE_URL)
    engine_kwargs: dict = {}
    if url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            # See apps/human_review_api/db/session.py::make_engine for why:
            # SQLite's default per-thread pool is fatal once a caller (e.g.
            # FastAPI, dispatching sync routes to a threadpool) touches the
            # engine from more than one thread.
            engine_kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **engine_kwargs)

    if engine.dialect.name == "postgresql":
        with engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _SCHEMA_LOCK_KEY})
            try:
                Base.metadata.create_all(bind=conn)
                conn.commit()
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _SCHEMA_LOCK_KEY})
                conn.commit()
    else:
        Base.metadata.create_all(engine)

    return engine


def make_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    engine = make_engine(database_url)
    return sessionmaker(bind=engine, expire_on_commit=False)
