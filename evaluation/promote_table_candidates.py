"""Fail-closed field-level promotion gate for reviewed table candidates."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path

import yaml

from packages.release_freeze import verify_release_manifest
from packages.table_contracts import PromotionEntry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--signature", required=True)
    args = parser.parse_args()
    config = yaml.safe_load(Path("config/table_shadow_v2.yaml").read_text())
    verify_release_manifest(Path(config["baseline_release"]))
    if not config["promotion_enabled"]:
        raise SystemExit("promotion disabled by table-shadow-v2 policy")
    secret = os.environ.get("TABLE_PROMOTION_SIGNING_KEY")
    if not secret:
        raise SystemExit("TABLE_PROMOTION_SIGNING_KEY is required")
    body = args.manifest.read_bytes()
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, args.signature):
        raise SystemExit("invalid promotion manifest signature")
    entries = [PromotionEntry.model_validate(item) for item in json.loads(body)]
    if not entries:
        raise SystemExit("empty promotion manifest")
    # Deliberately produces an eligibility artifact, never mutates final outputs.
    output = Path("evaluation_results/table_shadow_v2/promotion_eligibility.json")
    output.write_text(json.dumps([item.model_dump(mode="json") for item in entries], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
