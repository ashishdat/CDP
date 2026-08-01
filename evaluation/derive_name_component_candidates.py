"""Derive name components from complete-name OCR without using truth."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from workers.field_candidates.name_interpretations import interpret_complete_name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads(args.candidates.read_text(encoding="utf-8"))
    manifest = json.loads(Path("evaluation_data/document_manifest.json").read_text())
    derived = []
    seen = set()
    for row in rows:
        field = row.get("field_name", "")
        if field not in {"patient_first", "patient_last"}:
            continue
        raw = str(row.get("normalized_value") or row.get("raw_value") or "").strip()
        if not raw or not _plausible_complete_name(raw):
            continue
        family = manifest.get(row["document_id"], {}).get("form_type", "")
        convention = "LAST_FIRST" if family in {"CMS1500", "UB04"} else "FIRST_LAST"
        interpretations = interpret_complete_name(raw, convention)
        if not interpretations:
            continue
        chosen = interpretations[0]
        value = chosen.first if field == "patient_first" else chosen.last
        value = re.sub(r"[^A-Za-z'-]", "", value).upper()
        key = (row["document_id"], field, value, row.get("model_name"),
               row.get("preprocessing_variant"))
        if len(value) < 1 or key in seen:
            continue
        seen.add(key)
        derived.append({**row, "raw_value": raw, "normalized_value": value,
            "candidate_authority": "REVIEW_ONLY",
            "regional_provenance": "COMPLETE_NAME_BLOCK",
            "derived_from": "complete_name_ocr_candidate",
            "parser": "complete_name_component_parser",
            "parser_version": "2",
            "validation_results": list(row.get("validation_results") or [])
                + ["component_parse_only", f"family_convention:{convention}"],
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(derived, indent=2), encoding="utf-8")
    print(json.dumps({"derived_candidates": len(derived),
        "ground_truth_loaded": False, "candidate_authority": "REVIEW_ONLY"}, indent=2))
    return 0


def _plausible_complete_name(value: str) -> bool:
    tokens = re.findall(r"[A-Za-z][A-Za-z'-]*", value)
    return len(tokens) >= 2 and not any(token.upper() in {
        "PATIENT", "ADDRESS", "STATE", "STREET", "CITY"
    } for token in tokens)


if __name__ == "__main__":
    raise SystemExit(main())
