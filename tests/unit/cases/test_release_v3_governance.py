"""Phase 2 release governance: V2 immutability, V3 candidate hashes, selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from packages.domain.enums import ClaimFormType
from packages.release_freeze import (
    load_release_manifest,
    sha256_file,
    verify_release_manifest,
)
from packages.release_selection import (
    UnknownReleaseError,
    active_release_from_env,
    select_release,
)
from packages.templates.registry import TemplateRegistry

FROZEN_CMS1500_V2_HASH = (
    "eda2d70ae53af7459bc6823afd13e22eeb6a2846a3426e887749545a70ee86e4"
)
V2_MANIFEST = Path("config/releases/extraction-v2.yaml")
V3_MANIFEST = Path("config/releases/extraction-v3.yaml")
CMS1500_V2 = Path("config/templates/cms1500_v02_12.yaml")
CMS1500_V3 = Path("config/templates/cms1500_v03.yaml")


def test_v2_cms1500_template_remains_immutable():
    assert sha256_file(CMS1500_V2) == FROZEN_CMS1500_V2_HASH
    manifest = load_release_manifest(V2_MANIFEST)
    assert (
        manifest["configuration_hashes"]["config/templates/cms1500_v02_12.yaml"]
        == FROZEN_CMS1500_V2_HASH
    )


def test_v2_checksums_still_match_via_verify_release_manifest():
    assert V2_MANIFEST.is_file()
    before = sha256_file(V2_MANIFEST)
    verify_release_manifest(V2_MANIFEST)
    after = sha256_file(V2_MANIFEST)
    assert before == after
    assert load_release_manifest(V2_MANIFEST)["status"] == "FROZEN"


def test_v3_hashes_are_correct():
    manifest = load_release_manifest(V3_MANIFEST)
    assert manifest["pipeline_version"] == "extraction-v3"
    assert manifest["status"] == "CANDIDATE"
    assert manifest["template_versions"]["cms1500"] == "03"
    assert manifest["supersedes_after_promotion"] == "extraction-v2"
    verify_release_manifest(V3_MANIFEST)
    expected = manifest["configuration_hashes"]["config/templates/cms1500_v03.yaml"]
    assert sha256_file(CMS1500_V3) == expected
    # V3 must not rewrite the frozen V2 template path/hash.
    assert "config/templates/cms1500_v02_12.yaml" not in manifest["configuration_hashes"]
    assert sha256_file(CMS1500_V2) == FROZEN_CMS1500_V2_HASH


def test_runtime_selection_explicitly_chooses_v2_or_v3():
    assert select_release("extraction-v2") == V2_MANIFEST
    assert select_release("extraction-v3") == V3_MANIFEST
    assert select_release(V2_MANIFEST) == V2_MANIFEST
    assert select_release(V3_MANIFEST) == V3_MANIFEST
    assert select_release(str(V3_MANIFEST)) == V3_MANIFEST


def test_no_silent_fallback_changes_configured_release(monkeypatch):
    # Unset env → safe default extraction-v2 (never silently V3).
    monkeypatch.delenv("CDP_RELEASE_MANIFEST", raising=False)
    monkeypatch.delenv("CDP_PIPELINE_RELEASE", raising=False)
    assert active_release_from_env() == V2_MANIFEST

    # Wrong / unknown name → error (no fallback to another release).
    with pytest.raises(UnknownReleaseError):
        select_release("extraction-v9-does-not-exist")
    with pytest.raises(UnknownReleaseError):
        active_release_from_env(
            {"CDP_PIPELINE_RELEASE": "not-a-real-release"}
        )

    # Cannot accidentally load V3 when V2 is configured.
    monkeypatch.setenv("CDP_PIPELINE_RELEASE", "extraction-v2")
    monkeypatch.delenv("CDP_RELEASE_MANIFEST", raising=False)
    assert active_release_from_env() == V2_MANIFEST
    assert active_release_from_env() != V3_MANIFEST

    monkeypatch.setenv("CDP_RELEASE_MANIFEST", str(V2_MANIFEST))
    monkeypatch.setenv("CDP_PIPELINE_RELEASE", "extraction-v3")
    # Manifest path takes precedence; V2 stays selected despite V3 in pipeline env.
    assert active_release_from_env() == V2_MANIFEST


def test_template_registry_lex_latest_and_release_pin():
    registry = TemplateRegistry.load_from_directory()
    v2 = registry.get("cms1500", "02-12")
    v3 = registry.get("cms1500", "03")
    assert v2.version == "02-12"
    assert v3.version == "03"
    # Lexicographic: "03" > "02-12"
    assert registry.latest_for_form_type(ClaimFormType.CMS1500).version == "03"
    pinned_v2 = registry.get_for_release(ClaimFormType.CMS1500, V2_MANIFEST)
    pinned_v3 = registry.get_for_release(ClaimFormType.CMS1500, V3_MANIFEST)
    assert pinned_v2.version == "02-12"
    assert pinned_v3.version == "03"
