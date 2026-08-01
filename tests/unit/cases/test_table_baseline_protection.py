from pathlib import Path

from packages.release_freeze import sha256_file, verify_release_manifest


def test_frozen_baseline_manifest_and_configuration_are_valid():
    release = Path("config/releases/extraction-v2.yaml")
    before = sha256_file(release)
    verify_release_manifest(release)
    after = sha256_file(release)
    assert before == after
