"""Engine/session factory for the review-tasks table. Same concurrent-startup
DDL race protection as ``apps.ingestion_api.db.session`` — a different lock
key so the two services' startups never contend with each other.

Production prefers MySQL (``mysql+pymysql://``); Postgres remains supported.
"""

from __future__ import annotations

import os

from sqlalchemy.orm import Session, sessionmaker

from apps.human_review_api.db.models import Base
from packages.db_engine import create_app_engine

DEFAULT_SQLITE_URL = "sqlite:///:memory:"
_SCHEMA_LOCK_KEY = 727275  # one more than ingestion_api's


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
