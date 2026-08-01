import pytest

from evaluation.initialize_trusted_postgres import initialize


def test_initializer_rejects_non_postgres(tmp_path):
    schema = tmp_path / "schema.sql"
    schema.write_text("CREATE TABLE x (id INTEGER);")
    with pytest.raises(ValueError, match="requires PostgreSQL"):
        initialize("sqlite:///:memory:", schema)
