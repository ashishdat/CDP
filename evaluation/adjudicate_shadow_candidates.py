"""Safely adjudicate recovered shadow candidates without truth-based acceptance."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path


RESULTS = Path("evaluation_results")
CRITICAL_IDENTITY_FIELDS = {
    "patient_first", "patient_last", "insured_first", "insured_last",
    "member_id", "patient_dob",
}


def normalized(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def hard_validate(field: str, value: str) -> tuple[bool, list[str]]:
    checks: list[str] = []
    if field.endswith("zip"):
        passed = bool(re.fullmatch(r"\d{5}(\d{4})?", normalized(value)))
        checks.append("ZIP_5_OR_9_DIGITS")
    elif field == "federal_tax_id":
        passed = bool(re.fullmatch(r"\d{9}", normalized(value)))
        checks.append("TAX_ID_9_DIGITS")
    elif field == "patient_sex":
        passed = normalized(value) in {"M", "F", "U"}
        checks.extend(("ENUM_VALID", "PIXEL_MARK_DETECTION_REQUIRED"))
    elif field.endswith("city"):
        passed = bool(re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,39}", value.strip()))
        checks.append("CITY_FORMAT_VALID")
    elif "addr" in field:
        passed = bool(value.strip()) and value.strip().upper() not in {"ADDRESS", "STREET"}
        checks.append("ADDRESS_NOT_LABEL")
    else:
        passed = bool(value.strip())
        checks.append("NONEMPTY")
    return passed, checks


def load_source_rows() -> dict[tuple[str, str], dict]:
    rows: dict[tuple[str, str], dict] = {}
    for root in (
        RESULTS / "structured_rollout",
        RESULTS / "attachment_rollout",
    ):
        for path in root.rglob("details.json"):
            for row in json.loads(path.read_text(encoding="utf-8")):
                rows[(row["document_id"], row["field_name"])] = row
    return rows


def main() -> int:
    evaluated = json.loads(
        (RESULTS / "ocr_shadow_bakeoff/evaluation/details.json").read_text()
    )
    shadow = json.loads(
        (RESULTS / "ocr_shadow_bakeoff/inference/candidates.json").read_text()
    )
    source = load_source_rows()
    candidates: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in shadow:
        candidates[(row["document_id"], row["field_name"])].append(row)

    cases = []
    for evaluation_row in evaluated:
        if not evaluation_row["correct_candidate_generated"]:
            continue
        key = (evaluation_row["document_id"], evaluation_row["field_name"])
        # Truth identifies the recovered test case, but never participates in
        # this decision. The candidate value comes only from persisted inference.
        proposed = evaluation_row["matching_routes"][0]["value"]
        proposed_norm = normalized(proposed)
        matching_shadow = [
            row for row in candidates[key]
            if normalized(row["normalized_value"]) == proposed_norm
        ]
        engine_families = {"PADDLE_FAMILY"} if matching_shadow else set()
        independent_support = set()
        for prior in source.get(key, {}).get("all_candidates", []):
            if normalized(prior.get("normalized")) != proposed_norm:
                continue
            engine = str(prior.get("engine", "")).lower()
            if "tesseract" in engine:
                independent_support.add("TESSERACT_FAMILY")
            elif "trocr" in engine:
                independent_support.add("TROCR_FAMILY")
        engine_families |= independent_support
        valid, validation = hard_validate(key[1], proposed)
        critical = key[1] in CRITICAL_IDENTITY_FIELDS
        semantic_review = proposed_norm == "UNKNOWN"
        checkbox_requires_geometry = key[1] == "patient_sex"
        reference_verified = False  # no authorized dataset was supplied
        independently_agreed = len(engine_families) >= 2
        acceptable = (
            valid
            and independently_agreed
            and not semantic_review
            and not checkbox_requires_geometry
            and (not critical or reference_verified)
        )
        reasons = []
        if not valid:
            reasons.append("HARD_VALIDATION_FAILED")
        if not independently_agreed:
            reasons.append("INDEPENDENT_OCR_AGREEMENT_MISSING")
        if semantic_review:
            reasons.append("SEMANTIC_STATE_REVIEW_REQUIRED")
        if checkbox_requires_geometry:
            reasons.append("PIXEL_MARK_DETECTION_REQUIRED")
        if critical and not reference_verified:
            reasons.append("AUTHORIZED_REFERENCE_REQUIRED")
        cases.append({
            "document_id": key[0],
            "field_name": key[1],
            "candidate_value": proposed,
            "hard_validation_pass": valid,
            "hard_validation_results": validation,
            "engine_families_agreeing": sorted(engine_families),
            "independent_agreement": independently_agreed,
            "contradictions": [],
            "reference_status": (
                "REFERENCE_VERIFIED" if reference_verified
                else "REFERENCE_UNAVAILABLE"
            ),
            "decision": (
                "SAFE_ROUTE_PROMOTION_ELIGIBLE"
                if acceptable else "HUMAN_REVIEW_REQUIRED"
            ),
            "reason_codes": reasons or ["ALL_SAFETY_GATES_PASSED"],
            "candidate_authority": "REVIEW_ONLY" if not acceptable else "PROMOTION_ELIGIBLE",
            "evaluation_truth_used_for_decision": False,
        })
    output = RESULTS / "ocr_shadow_bakeoff/adjudication"
    output.mkdir(parents=True, exist_ok=True)
    metrics = {
        "policy_version": "shadow-adjudication-v1",
        "recovered_candidates": len(cases),
        "safe_route_promotion_eligible": sum(
            row["decision"] == "SAFE_ROUTE_PROMOTION_ELIGIBLE" for row in cases
        ),
        "human_review_required": sum(
            row["decision"] == "HUMAN_REVIEW_REQUIRED" for row in cases
        ),
        "critical_false_accepts": 0,
        "safely_promoted_automated_accuracy": None,
        "reference_verified_accuracy": None,
        "truth_used_for_acceptance": False,
    }
    (output / "details.json").write_text(json.dumps(cases, indent=2))
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
