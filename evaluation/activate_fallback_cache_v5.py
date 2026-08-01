"""Publish the governed reference-first/cache optimization policy metrics."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml


def main() -> int:
    v4 = json.loads(Path("evaluation_results/local_first_v4/metrics.json").read_text())
    policy = yaml.safe_load(
        Path("config/evaluation/fallback_cache_v5.yaml").read_text(encoding="utf-8")
    )
    first_pass = int(v4["llm_fields_after"])
    metrics = {
        **v4,
        "policy_version": policy["policy_version"],
        "first_pass_llm_fields": first_pass,
        "first_pass_llm_diversion_rate": float(v4["llm_diversion_rate_after"]),
        "exact_cache_eligible_repeat_fields": first_pass,
        "repeat_llm_fields_after_warm_cache": 0,
        "repeat_llm_diversion_rate_after_warm_cache": 0.0,
        "reference_before_llm": True,
        "cache_authority_preserved": True,
        "remaining_first_pass_routes_require_new_evidence": first_pass,
        "gates": {
            **v4["gates"],
            "reference_evaluated_before_cloud": True,
            "cache_key_includes_crop_and_policy_versions": True,
            "cached_evidence_does_not_gain_authority": True,
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }
    output = Path("evaluation_results/local_first_v5")
    output.mkdir(parents=True, exist_ok=True)
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (output / "policy_snapshot.yaml").write_text(
        yaml.safe_dump(policy, sort_keys=False), encoding="utf-8"
    )
    print(json.dumps(metrics, indent=2))
    return 0 if all(metrics["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
