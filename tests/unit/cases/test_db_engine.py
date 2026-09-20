"""Unit tests for shared DB engine URL helpers."""

from packages.db_engine import looks_like_mysql, looks_like_postgres, looks_like_sqlite


def test_url_dialect_helpers():
    assert looks_like_mysql("mysql+pymysql://u:p@h/db")
    assert looks_like_postgres("postgresql+psycopg://u:p@h/db")
    assert looks_like_sqlite("sqlite:///:memory:")
    assert not looks_like_mysql("postgresql+psycopg://u:p@h/db")
    assert not looks_like_postgres("mysql+pymysql://u:p@h/db")
