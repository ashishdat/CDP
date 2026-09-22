"""Filesystem object store for Docker-less UI demos."""

from pathlib import Path

from packages.storage.object_store import FilesystemObjectStore, build_object_store


def test_filesystem_object_store_roundtrip(tmp_path: Path):
    store = FilesystemObjectStore(tmp_path)
    store.ensure_bucket("idp-documents")
    ref = store.put_immutable("idp-documents", "a/b/c.png", b"hello", content_type="image/png")
    assert store.exists("idp-documents", "a/b/c.png")
    assert store.get_bytes(ref) == b"hello"
    assert ref.sha256
    assert store.signed_get_url(ref).startswith("file://")


def test_build_object_store_filesystem(tmp_path: Path):
    store = build_object_store(backend="filesystem", filesystem_root=str(tmp_path))
    store.ensure_bucket("b")
    store.put_immutable("b", "k", b"x")
    assert store.exists("b", "k")


def test_production_rejects_filesystem_backend():
    from packages.production_runtime import validate_production_settings
    from packages.settings import Settings

    result = validate_production_settings(
        Settings(
            database_url="mysql+pymysql://idp:secret@db:3306/idp",
            use_in_memory_bus=False,
            object_store_access_key="prod-key",
            object_store_secret_key="prod-secret",
            object_store_backend="filesystem",
        )
    )
    assert not result.ok
    assert any(i.code == "FILESYSTEM_OBJECT_STORE_FORBIDDEN" for i in result.issues)
