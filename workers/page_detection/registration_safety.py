"""Safety observations only; never authorize registration or alter a threshold."""

import json
from html import escape
from pathlib import Path

from workers.page_detection.registration_telemetry import ACTIVE


def record(name, measured, expected, passed, *, inputs=None, provenance="LIVE_GATE"):
    delta = None
    if isinstance(measured, (int, float)) and not isinstance(measured, bool) and expected:
        if "min" in expected and measured < expected["min"]:
            delta = measured - expected["min"]
        elif "max" in expected:
            delta = measured - expected["max"]
        elif "min" in expected:
            delta = measured - expected["min"]
    check = {"check": name, "input": inputs if inputs is not None else {"measured_value": measured}, "output": passed,
             "threshold": expected, "expected": expected, "actual": measured,
             "measured_value": measured, "pass": passed,
             "fail": not passed if passed is not None else None,
             "delta": delta, "provenance": provenance,
             "status": "NOT_ENFORCED" if passed is None else ("PASS" if passed else "FAIL")}
    trace = ACTIVE.get()
    if trace is not None:
        trace.emit(trace.current or "Acceptance", "OBSERVED", safety_check=check)
    return check


def write_saved_report(document_path, directory):
    """Explain saved evidence without rerunning gates or inventing live events."""
    document = json.loads(Path(document_path).read_text(encoding="utf-8"))
    attempts = []
    for candidate in document["template_selection"]["candidate_templates"]:
        diagnostic = candidate.get("diagnostics", {})
        evidence = diagnostic.get("registration_evidence")
        policy = diagnostic.get("registration_policy")
        if not evidence or not policy:
            continue
        reasons = (evidence.get("rejection_reason") or "").split(",")
        checks = []
        specs = [
            ("Inlier count", "inlier_count", {"min": policy["min_inliers"]}, "insufficient_inliers"),
            ("Inlier ratio", "inlier_ratio", {"min": policy["min_inlier_ratio"]}, "low_inlier_ratio"),
            ("Residual", "reprojection_error", {"max": policy["max_reprojection_error"]}, "high_reprojection_error"),
            ("Coverage", "coverage_ratio", {"min": policy["min_coverage_ratio"]}, "low_coverage"),
            ("Scale", "scale_change", {"min": policy["min_scale"], "max": policy["max_scale"]}, "unsafe_scale_change"),
            ("Rotation", "rotation_degrees", {"max": policy["max_abs_rotation_degrees"]}, "unsafe_rotation"),
            ("Perspective", "perspective_distortion", {"max": policy["max_perspective_distortion"]}, "unsafe_perspective_distortion"),
            ("Transformed corners", "corner_validity", {"equals": True}, "invalid_transformed_corners"),
        ]
        for name, key, threshold, reason in specs:
            value = evidence.get(key)
            if value is None:
                checks.append({"check": name, "status": "UNAVAILABLE", "actual": None,
                               "expected": threshold, "delta": None})
                continue
            # The saved rejection reasons are the authority for pass/fail.
            # Values absent from early exits are never treated as passing gates.
            reached = evidence.get("algorithm") == "sift_flann_ransac_homography" and evidence.get("transform_matrix") is not None
            if reached:
                checks.append(record(name, abs(value) if name == "Rotation" else value,
                                     threshold, reason not in reasons,
                                     inputs={key: value}, provenance="SAVED_GATE_OUTCOME"))
            else:
                checks.append({"check": name, "status": "UNAVAILABLE", "actual": value,
                               "expected": threshold, "delta": None})
        for name in ("Transform determinant", "Aspect ratio", "Translation", "Anchor spread", "Homography condition"):
            checks.append({"check": name, "status": "UNAVAILABLE" if name == "Aspect ratio" else "NOT_ENFORCED",
                           "actual": None, "expected": None, "delta": None,
                           "reason": "No standalone gate in the SIFT acceptance policy; aspect ratio belongs to the separate cheap path"})
        attempts.append({"template_id": candidate["template_id"], "page": candidate["page_number"],
                         "first_failing_safety_check": next((c["check"] for c in checks if c["status"] == "FAIL"), None),
                         "recorded_rejection_reason": evidence.get("rejection_reason"), "checks": checks})
    report = {"source": str(document_path), "source_type": "PREVIOUSLY_RECORDED_EVIDENCE_NO_RETRY",
              "attempts": attempts,
              "notes": ["No live gate events were present in this historical run. No history has been relabelled as live telemetry.",
                        "Deltas are actual minus the violated bound; rotation uses absolute degrees.",
                        "Anchor spread is not the same as inlier coverage. No threshold is invented for an unenforced diagnostic.",
                        "First failing safety check refers to the final SIFT acceptance gates, not earlier cheap-alignment fallback."]}
    payload = json.dumps(report, indent=2, allow_nan=False)
    directory = Path(directory)
    (directory / "registration_safety.json").write_text(payload + "\n", encoding="utf-8")
    (directory / "registration_safety.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Registration safety</title>'
        '<body><h1>Registration safety</h1><pre>' + escape(payload) + '</pre></body></html>', encoding="utf-8")
    return report
