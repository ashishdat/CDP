"""Generate review-only CMS candidates from labeled page-token regions."""

from __future__ import annotations

import json
import re
from pathlib import Path


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" ,.")


def main() -> int:
    source_root = Path("evaluation_results/assets")
    output = Path("evaluation_results/cms_page_token_recovery")
    output.mkdir(parents=True, exist_ok=True)
    candidates = []
    for source in sorted(source_root.glob("A-*.source-v2.ocr.json")):
        document_id = source.name.split(".")[0]
        tokens = json.loads(source.read_text(encoding="utf-8"))
        name_tokens = sorted(
            (token for token in tokens if token["x0"] < 600 and 40 <= token["y0"] <= 72),
            key=lambda token: token["x0"],
        )
        name = _clean(" ".join(token["text"] for token in name_tokens))
        parts = [_clean(part) for part in re.split(r"[,.;]+|\s{2,}", name) if _clean(part)]
        if len(parts) == 1:
            words = parts[0].split()
            parts = [words[0], " ".join(words[1:])] if len(words) > 1 else parts
        if len(parts) >= 2:
            candidates.extend([
                _candidate(document_id, "patient_last", parts[0], source, "cms_name_region"),
                _candidate(document_id, "patient_first", parts[1].split()[0], source, "cms_name_region"),
            ])
        regions = {
            "patient_state": (520, 640, 165, 205),
            "insured_city": (1000, 1450, 165, 210),
            "insured_state": (1450, 1600, 160, 205),
        }
        for field, (x0, x1, y0, y1) in regions.items():
            values = [
                _clean(token["text"]) for token in tokens
                if x0 <= token["x0"] <= x1 and y0 <= token["y0"] <= y1
            ]
            values = [
                value for value in values
                if value and value.upper() not in {"STATE", "CITY", "INFORMATION"}
            ]
            for value in values:
                candidates.append(
                    _candidate(document_id, field, value, source, "cms_labeled_region")
                )
    (output / "candidates.json").write_text(
        json.dumps(candidates, indent=2), encoding="utf-8"
    )
    print(json.dumps({"review_only_candidates": len(candidates)}, indent=2))
    return 0


def _candidate(document_id, field, value, source, reason):
    return {
        "document_id": document_id,
        "field_name": field,
        "raw_value": value,
        "normalized": value,
        "provider": "paddle_page_token_recovery",
        "accepted": False,
        "validation_results": ["NEEDS_REVIEW"],
        "selection_reason": reason,
        "source": str(source),
    }


if __name__ == "__main__":
    raise SystemExit(main())
