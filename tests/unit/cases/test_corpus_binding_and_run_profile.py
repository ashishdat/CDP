"""Permanent guards: corpus zip↔dataset bind + FAST vs PRODUCT gate."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from packages.corpus_binding import CorpusBindingError, bind_corpus
from packages.product_gates.similar_sample_gate import evaluate_similar_sample_gate
from packages.run_profiles import (
    apply_profile_env,
    detect_live_profile,
    gate_allows_profile,
    write_run_manifest,
)


def _tiny_zip(path: Path, names: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name in names:
            zf.writestr(name, b"fake-image-bytes")


def test_bind_corpus_rejects_zip_dataset_mismatch(tmp_path: Path):
    z1 = tmp_path / "a.zip"
    z2 = tmp_path / "b.zip"
    _tiny_zip(z1, ["Group A/DOC.001"])
    _tiny_zip(z2, ["Group A/DOC.001"])
    ds = tmp_path / "dataset.yaml"
    ds.write_text(
        "\n".join(
            [
                "dataset_id: DEVELOPMENT_DATASET_V1",
                f"root: {z1}",
                "pages: 2173",
                "documents: 1000",
                "description: 'Hackathon claims development corpus; not ENGINEERING_BENCHMARK_V1.'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    # pages/documents won't match registry if we use DatasetManager — bind_corpus
    # only reads root + dataset_id from yaml, so this is fine.
    with pytest.raises(CorpusBindingError, match="CORPUS_ZIP_DATASET_MISMATCH"):
        bind_corpus(dataset_yaml=ds, zip_path=z2, documents=["Group A/DOC.001"])


def test_bind_corpus_rejects_missing_documents(tmp_path: Path):
    z1 = tmp_path / "a.zip"
    _tiny_zip(z1, ["Group A/DOC.001"])
    ds = tmp_path / "dataset.yaml"
    ds.write_text(
        "\n".join(
            [
                "dataset_id: DEVELOPMENT_DATASET_HACKATHON_5000_V1",
                f"root: {z1}",
                "pages: 10341",
                "documents: 5000",
                "description: 'Hackathon 5000 Claims Drive corpus "
                "(id=1ohv3muiEChPU6pqR0sj7ansqUYq7odIY); not ENGINEERING_BENCHMARK_V1.'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CorpusBindingError, match="CORPUS_DOCUMENTS_MISSING"):
        bind_corpus(
            dataset_yaml=ds,
            zip_path=z1,
            documents=["Group A/DOC.001", "Group A/MISSING.999"],
        )


def test_bind_corpus_ok_when_aligned(tmp_path: Path):
    z1 = tmp_path / "a.zip"
    _tiny_zip(z1, ["Group A/DOC.001", "Group B/DOC.002"])
    ds = tmp_path / "dataset.yaml"
    ds.write_text(
        "\n".join(
            [
                "dataset_id: DEVELOPMENT_DATASET_HACKATHON_5000_V1",
                f"root: {z1}",
                "pages: 10341",
                "documents: 5000",
                "description: 'Hackathon 5000 Claims Drive corpus "
                "(id=1ohv3muiEChPU6pqR0sj7ansqUYq7odIY); not ENGINEERING_BENCHMARK_V1.'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = bind_corpus(
        dataset_yaml=ds,
        zip_path=z1,
        documents=["Group A/DOC.001", "Group B/DOC.002"],
    )
    assert result.documents_present == 2
    assert result.zip_matches_dataset_root is True


def test_fast_profile_not_gate_eligible(tmp_path: Path):
    write_run_manifest(tmp_path, profile="FAST", dataset_id="X")
    man = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))
    ok, reason = gate_allows_profile(man)
    assert ok is False
    assert "FAST_NOT_GATE_ELIGIBLE" in reason


def test_product_profile_gate_eligible(tmp_path: Path):
    write_run_manifest(tmp_path, profile="PRODUCT", dataset_id="X")
    man = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))
    ok, reason = gate_allows_profile(man)
    assert ok is True
    assert reason == "PRODUCT"


def test_tip_seed_requires_allow():
    ok, reason = gate_allows_profile({"profile": "TIP_SEED"})
    assert ok is False
    assert "TIP_SEED_REQUIRES_ALLOW" in reason
    ok2, _ = gate_allows_profile({"profile": "TIP_SEED"}, allow_tip_seed=True)
    assert ok2 is True


def test_product_gate_refuses_fast_ledger_even_if_stp_high():
    rows = {
        f"stp_{i}": {"disposition": "TRUE_STP", "claim_id": f"stp_{i}"}
        for i in range(100)
    }
    result = evaluate_similar_sample_gate(
        rows,
        allow_incomplete_gt=True,
        run_manifest={"profile": "FAST", "gate_eligible": False},
    )
    assert result.pass_gate is False
    assert any("FAST_NOT_GATE_ELIGIBLE" in r for r in result.reasons)


def test_product_gate_passes_with_product_manifest():
    rows = {
        f"stp_{i}": {"disposition": "TRUE_STP", "claim_id": f"stp_{i}"}
        for i in range(100)
    }
    result = evaluate_similar_sample_gate(
        rows,
        allow_incomplete_gt=True,
        run_manifest={"profile": "PRODUCT", "gate_eligible": True},
    )
    assert result.pass_gate is True
    assert any("PRODUCT_GATE_PASS" in r for r in result.reasons)


def test_apply_profile_env_sets_residual_kill_switches():
    env, profile = apply_profile_env("FAST", {})
    assert profile.name == "FAST"
    assert env["CDP_GPT4O_CROP_RESIDUAL"] == "0"
    assert env["CDP_AZURE_DI_CHARGE_RESIDUAL"] == "0"
    env2, profile2 = apply_profile_env("PRODUCT", {})
    assert profile2.name == "PRODUCT"
    assert env2["CDP_GPT4O_CROP_RESIDUAL"] == "1"
    assert detect_live_profile(env2) == "PRODUCT"
    assert detect_live_profile(env) == "FAST"
