"""Create the non-destructive trusted-claims contract in PostgreSQL."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from sqlalchemy import create_engine, text


def initialize(database_url: str, schema_path: Path) -> None:
    engine = create_engine(database_url)
    if engine.dialect.name != "postgresql":
        raise ValueError("trusted claims initialization requires PostgreSQL")
    sql = schema_path.read_text(encoding="utf-8")
    with engine.begin() as connection:
        connection.execute(text(sql))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url-env", default="DOWNSTREAM_CLAIMS_DATABASE_URL")
    parser.add_argument(
        "--schema", type=Path,
        default=Path("deploy/postgres/trusted-claims-init.sql"),
    )
    args = parser.parse_args()
    database_url = os.getenv(args.database_url_env) or os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("set DOWNSTREAM_CLAIMS_DATABASE_URL or DATABASE_URL")
    initialize(database_url, args.schema)
    print("trusted PostgreSQL claims schema is ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
