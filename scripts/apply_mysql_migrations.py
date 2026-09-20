#!/usr/bin/env python3
"""Apply MySQL platform migrations idempotently.

Usage:
  export DATABASE_URL=mysql+pymysql://idp:secret@127.0.0.1:3306/idp
  python3 scripts/apply_mysql_migrations.py
  python3 scripts/apply_mysql_migrations.py --dry-run

Skips statements that fail with MySQL duplicate-column / duplicate-key
errors so re-runs are safe. Records applied file names in schema_migrations.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MIGRATIONS_DIR = ROOT / "deploy" / "mysql" / "migrations"

# MySQL errno: Duplicate column name / Duplicate key name / table exists
_SKIP_ERRNOS = {1050, 1060, 1061}


def _split_statements(sql: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(buf).strip().rstrip(";").strip())
            buf = []
    if buf:
        statements.append("\n".join(buf).strip().rstrip(";").strip())
    return [s for s in statements if s]


def apply_migrations(database_url: str, *, dry_run: bool = False) -> int:
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError, ProgrammingError

    if not database_url.casefold().startswith("mysql"):
        print(
            "FAIL DATABASE_URL must be mysql+pymysql://... for this applicator",
            file=sys.stderr,
        )
        return 1

    engine = create_engine(database_url)
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print(f"FAIL no migrations in {MIGRATIONS_DIR}", file=sys.stderr)
        return 1

    applied = 0
    skipped = 0
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename VARCHAR(255) NOT NULL PRIMARY KEY,
                    applied_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )
        already = {
            row[0]
            for row in conn.execute(text("SELECT filename FROM schema_migrations"))
        }

        for path in files:
            if path.name in already:
                print(f"SKIP already applied {path.name}")
                skipped += 1
                continue
            sql = path.read_text(encoding="utf-8")
            statements = _split_statements(sql)
            print(f"APPLY {path.name} ({len(statements)} statements)")
            if dry_run:
                continue
            for stmt in statements:
                try:
                    conn.execute(text(stmt))
                except (OperationalError, ProgrammingError) as exc:
                    orig = getattr(exc, "orig", None)
                    errno = getattr(orig, "args", [None])[0]
                    if errno in _SKIP_ERRNOS:
                        print(f"  idempotent skip errno={errno}")
                        continue
                    raise
            conn.execute(
                text("INSERT INTO schema_migrations (filename) VALUES (:f)"),
                {"f": path.name},
            )
            applied += 1

    print(f"done applied={applied} skipped={skipped} dry_run={dry_run}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="MySQL SQLAlchemy URL (default: DATABASE_URL env)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        print("FAIL set DATABASE_URL or --database-url", file=sys.stderr)
        return 1
    return apply_migrations(args.database_url, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
