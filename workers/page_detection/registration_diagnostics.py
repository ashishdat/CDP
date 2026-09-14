"""Registration reporting only: no matching, retries, OCR or policy decisions."""

import base64
import json
from html import escape
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

FAILURES = {
    "insufficient_edge_structure": "Feature Matching",
    "insufficient_keypoints": "Feature Matching",
    "insufficient_good_matches": "Feature Matching",
    "homography_not_found": "Homography",
    "insufficient_inliers": "Homography",
    "low_inlier_ratio": "Homography",
    "high_reprojection_error": "Transform",
    "unsafe_scale_change": "Transform",
    "unsafe_rotation": "Transform",
    "unsafe_perspective_distortion": "Transform",
    "invalid_transformed_corners": "Transform",
    "aspect_ratio_mismatch": "Transform",
    "low_coverage": "Acceptance",
    "cheap_confidence_below_threshold": "Acceptance",
    "template_lineage_mismatch": "Acceptance",
}
ORDER = ("Anchor Detection", "Feature Matching", "Homography", "Transform", "Acceptance")


def build_report(document):
    attempts = []
    candidates = (document.get("template_selection") or {}).get("candidate_templates", [])
    records = []
    for candidate in candidates:
        diagnostic = candidate.get("diagnostics", {})
        if diagnostic.get("cheap_registration_evidence") is not None:
            records.append((candidate, diagnostic["cheap_registration_evidence"], "selection_cheap"))
        if "registration" in candidate.get("scores", {}):
            records.append((candidate, diagnostic.get("registration_evidence"), "selection_final"))
    registration = document.get("registration") or {}
    if registration.get("evidence"):
        records.append((registration, registration["evidence"], "selected_template_registration"))
    for index, (candidate, raw, origin) in enumerate(records, 1):
        evidence = raw or {}
        diagnostic = candidate.get("diagnostics", {})
        reasons = (evidence.get("rejection_reason") or "").split(",")
        known = {FAILURES[reason] for reason in reasons if reason in FAILURES}
        first = next((stage for stage in ORDER if stage in known), None)
        policy = diagnostic.get("registration_policy") or candidate.get("registration_policy")
        score = evidence.get("alignment_confidence", candidate.get("scores", {}).get("registration"))
        threshold = (diagnostic.get("thresholds") or {}).get("registration")
        algorithm = evidence.get("algorithm")
        if algorithm == "edge_phase_correlation":
            threshold = policy.get("cheap_min_confidence") if policy else None
        attempts.append({
            "attempt": index, "origin": origin, "template_id": candidate.get("template_id"),
            "page_number": candidate.get("page_number"), "algorithm": algorithm,
            "anchor_detection": {"anchor_count": diagnostic.get("anchor_count"),
                                 "anchor_matches": diagnostic.get("matched_anchor_phrases"),
                                 "expected_anchors": diagnostic.get("expected_anchors"),
                                 "coordinates": None},
            "feature_matching": {"feature_count": evidence.get("keypoints_source"),
                                 "template_feature_count": evidence.get("keypoints_template"),
                                 "matched_features": evidence.get("good_matches"),
                                 "coordinates": None},
            "homography": {"inliers": evidence.get("inlier_count"),
                           "score": evidence.get("homography_quality"), "inlier_coordinates": None},
            "transform": {"matrix": evidence.get("transform_matrix"),
                          "residual": evidence.get("reprojection_error"),
                          "alignment_error": evidence.get("reprojection_error"),
                          "error_definition": "Recorded mean inlier reprojection error in pixels; no independent alignment residual computed"},
            "acceptance": {"accepted": evidence.get("accepted"), "score": score,
                           "threshold": threshold,
                           "delta_to_threshold": score - threshold if score is not None and threshold is not None else None,
                           "policy": policy, "reason": evidence.get("rejection_reason"),
                           "note": "Scalar threshold is only one gate; recorded policy contains other acceptance gates"},
            "first_failing_stage": first,
            "first_failing_stage_status": "RECORDED" if first else (
                "NOT_APPLICABLE" if evidence.get("accepted") else "UNAVAILABLE"),
            "raw_evidence": raw,
        })
    return {"report_type": "RegistrationReport", "document_id": document.get("document_id"),
            "attempt_count": len(attempts), "attempts": attempts,
            "notes": ["Only recorded attempts are reported; earlier unrecorded subattempts cannot be reconstructed.",
                      "Null means unavailable. A historical scalar score cannot establish the first failing stage.",
                      "Feature and inlier coordinates are not exposed by the existing registration result.",
                      "No registration retry, OCR, geometry stage or threshold change performed."]}


def write_report(document, directory):
    report = build_report(document)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    source = document.get("source", {})
    previews = {}
    try:
        if source.get("archive") and source.get("entry"):
            with ZipFile(source["archive"], "r") as archive:
                payload = archive.read(source["entry"])
            with Image.open(BytesIO(payload)) as image:
                for page in sorted({attempt["page_number"] for attempt in report["attempts"]
                                    if attempt["page_number"] is not None}):
                    image.seek(page - 1)
                    buffer = BytesIO()
                    image.convert("RGB").save(buffer, format="PNG")
                    previews[page] = base64.b64encode(buffer.getvalue()).decode("ascii")
    except (OSError, ValueError, KeyError, EOFError) as exc:
        report["preview_error"] = type(exc).__name__
    panels = []
    for attempt in report["attempts"]:
        preview = previews.get(attempt["page_number"])
        original = (f'<img style="max-width:100%;max-height:480px" src="data:image/png;base64,{preview}" alt="Original page">'
                    if preview else '<p>Original unavailable</p>')
        panels.append(f'<h2>Attempt {attempt["attempt"]}: {escape(str(attempt["template_id"]))}</h2>'
                      '<div style="display:flex;gap:16px;overflow:auto">'
                      f'<section style="min-width:280px"><h3>Original</h3>{original}</section>')
        for title, reason in (
            ("Anchor Overlay", "Anchor coordinates were not recorded."),
            ("Feature Overlay", "Feature coordinates were not recorded."),
            ("Homography Overlay", "Inlier correspondences were not recorded."),
            ("Final Transform", "Transformed raster was not retained. Recorded matrix is shown below; no transform was rerun."),
        ):
            panels.append(f'<section style="min-width:200px"><h3>→ {title}</h3><p>Unavailable: {reason}</p></section>')
        panels.append('</div><pre>' + escape(json.dumps(attempt, indent=2)) + '</pre>')
    payload = json.dumps(report, indent=2, allow_nan=False)
    (directory / "registration_report.json").write_text(payload + "\n", encoding="utf-8")
    html = ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Registration diagnostics</title>'
            '<body><h1>Registration diagnostics</h1><p>Recorded evidence only; missing overlays are not reconstructed.</p>'
            + ''.join(panels) + '<h2>Report</h2><pre>' + escape(payload) + '</pre></body></html>')
    (directory / "registration_report.html").write_text(html, encoding="utf-8")
    return report
