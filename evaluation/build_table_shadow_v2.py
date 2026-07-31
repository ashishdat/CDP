"""Build truth-free normalized candidates with baseline checksum protection."""

from __future__ import annotations

import json
from pathlib import Path

from packages.release_freeze import sha256_file, verify_release_manifest
from workers.table_extraction.pipeline import normalize_artifacts


def main() -> int:
    release = Path("config/releases/extraction-v2.yaml")
    verify_release_manifest(release)
    before = sha256_file(release)
    count = normalize_artifacts(
        Path("evaluation_results/img2table_shadow/artifacts.json"),
        Path("evaluation_results/table_shadow_v2/artifacts"),
        Path("evaluation_results/table_shadow_v2/candidates.jsonl"),
    )
    verify_release_manifest(release)
    after = sha256_file(release)
    if before != after:
        raise RuntimeError("frozen baseline checksum changed")
    payload = {
        "candidates": count,
        "baseline_manifest_sha256_before": before,
        "baseline_manifest_sha256_after": after,
        "baseline_unchanged": before == after,
        "evaluation_truth_loaded": False,
    }
    path = Path("evaluation_results/table_shadow_v2/checksum_verification.json")
    path.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
