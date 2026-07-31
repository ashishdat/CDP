"""Engine/session factory for the review-tasks table. Same
concurrent-startup DDL race protection as `apps.ingestion_api.db.session`
(see that module's docstring) -- a different advisory-lock key so the two
services' startups never contend with each other."""

from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.human_review_api.db.models import Base

DEFAULT_SQLITE_URL = "sqlite:///:memory:"
_SCHEMA_LOCK_KEY = 727275  # one more than ingestion_api's -- see that module


def make_engine(database_url: str | None = None):
    url = database_url or os.environ.get("DATABASE_URL", DEFAULT_SQLITE_URL)
    engine_kwargs: dict = {}
    if url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            # SQLite's default per-thread pool hands each thread its own
            # empty :memory: database -- fatal when a caller (e.g. FastAPI,
            # which runs sync route handlers in a threadpool) accesses the
            # same engine from more than one thread. StaticPool keeps a
            # single shared connection for the engine's whole lifetime.
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
