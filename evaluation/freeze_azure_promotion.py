"""Freeze Azure promotion inputs without persisting credentials."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from evaluation.reporting_v3_common import canonical_json, sha256_bytes, sha256_file


def main() -> int:
    config_path = Path("config/evaluation/azure_promotion_freeze.yaml")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    source_paths = {
        "normalization_rules": Path(config["normalization_policy"]),
        "validation_policy": Path(config["validation_policy"]),
        "prompt_schema": Path("workers/vlm_fallback/schema.py"),
        "prompt_adapter": Path("workers/vlm_fallback/adapter.py"),
        "crop_runner": Path("evaluation/run_azure_vlm_shadow.py"),
    }
    manifest = {
        "freeze_version": config["freeze_version"],
        "created_at": datetime.now(UTC).isoformat(),
        "configuration": config,
        "source_checksums": {
            name: sha256_file(path) for name, path in source_paths.items()
        },
        "secrets_persisted": False,
    }
    manifest["freeze_sha256"] = sha256_bytes(canonical_json(manifest))
    output = Path("evaluation_data/contracts/azure_promotion_freeze_v1.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    output.with_suffix(".sha256").write_text(
        manifest["freeze_sha256"] + "\n", encoding="ascii"
    )
    print(json.dumps({
        "freeze_version": manifest["freeze_version"],
        "freeze_sha256": manifest["freeze_sha256"],
        "secrets_persisted": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
