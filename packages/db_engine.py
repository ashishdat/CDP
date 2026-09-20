"""Shared SQLAlchemy engine helpers (SQLite / MySQL / Postgres).

Production prefers MySQL (``mysql+pymysql://...``). Postgres remains supported
for legacy deploys. SQLite is for unit tests only.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool


def looks_like_sqlite(url: str) -> bool:
    lowered = (url or "").strip().casefold()
    return lowered.startswith("sqlite:") or ":memory:" in lowered


def looks_like_mysql(url: str) -> bool:
    lowered = (url or "").strip().casefold()
    return lowered.startswith("mysql:") or "+pymysql://" in lowered or "+mysqldb://" in lowered


def looks_like_postgres(url: str) -> bool:
    lowered = (url or "").strip().casefold()
    return (
        lowered.startswith("postgresql:")
        or lowered.startswith("postgres:")
        or "+psycopg" in lowered
    )


def create_app_engine(
    url: str,
    *,
    metadata_create_all: Callable[[Engine], None] | None = None,
    schema_lock_key: int = 727274,
) -> Engine:
    """Create an engine and ensure ORM metadata exists (dev-friendly).

    Concurrent startup uses dialect-native advisory locks so multiple
    services do not race ``create_all`` on a cold database.
    """
    engine_kwargs: dict = {}
    if looks_like_sqlite(url):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            engine_kwargs["poolclass"] = StaticPool

    engine = create_engine(url, **engine_kwargs)
    create_all = metadata_create_all
    if create_all is None:
        return engine

    dialect = engine.dialect.name
    if dialect == "postgresql":
        with engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": schema_lock_key})
            try:
                create_all(conn)  # type: ignore[arg-type]
                conn.commit()
            finally:
                conn.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": schema_lock_key}
                )
                conn.commit()
        return engine

    if dialect == "mysql":
        lock_name = f"cdp_schema_{schema_lock_key}"
        with engine.connect() as conn:
            conn.execute(text("SELECT GET_LOCK(:name, 60)"), {"name": lock_name})
            try:
                create_all(conn)  # type: ignore[arg-type]
                conn.commit()
            finally:
                conn.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
                conn.commit()
        return engine

    create_all(engine)
    return engine
