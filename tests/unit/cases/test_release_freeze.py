from pathlib import Path

import pytest
import yaml

from packages.release_freeze import sha256_file, verify_release_manifest


def test_frozen_manifest_detects_unversioned_configuration_change(tmp_path, monkeypatch):
    config = tmp_path / "policy.yaml"
    config.write_text("version: 1\n")
    manifest = tmp_path / "release.yaml"
    manifest.write_text(yaml.safe_dump({
        "status": "FROZEN",
        "configuration_hashes": {"policy.yaml": sha256_file(config)},
    }))
    monkeypatch.chdir(tmp_path)
    verify_release_manifest(Path("release.yaml"))
    config.write_text("version: 2\n")
    with pytest.raises(ValueError, match="new release"):
        verify_release_manifest(Path("release.yaml"))
