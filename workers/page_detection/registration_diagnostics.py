"""Registration reporting only: no matching, retries, OCR or policy decisions."""

import base64
import json
from html import escape
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from PIL import Image


def build_report(document):
    """Consume emitted events only; absent traces never become reconstructed attempts."""
    attempts = []
    traces = (document.get("registration_trace") or {}).get("traces", [])
    for index, trace in enumerate(traces, 1):
        events = trace["events"]
        finished = next((event for event in reversed(events)
                         if event["stage"] == "Registration Finished"), {})
        evidence = finished.get("data", {}).get("evidence") or {}
        failure = next((event for event in events if event["status"] == "FAILED"
                        and event["stage"] != "Registration Finished"), None)
        def value(key, events=events):
            return next((event[key] for event in reversed(events)
                         if event.get(key) is not None), None)
        def data(key, events=events):
            return next((event["data"][key] for event in reversed(events)
                         if event.get("data", {}).get(key) is not None), None)
        acceptance_start = next((event for event in reversed(events)
                                 if event["stage"] == "Acceptance" and event["status"] == "STARTED"), {})
        threshold = acceptance_start.get("data", {}).get("threshold")
        confidence = evidence.get("alignment_confidence")
        attempts.append({
            "attempt": index, "origin": "RegistrationTrace", "trace_id": trace["trace_id"],
            "template_id": data("template_id"), "page_number": data("page_number"),
            "algorithm": evidence.get("algorithm"),
            "anchor_detection": {"anchor_count": value("anchor_count"), "anchor_matches": data("anchor_matches"),
                                 "expected_anchors": data("expected_anchors"), "coordinates": None},
            "feature_matching": {"feature_count": value("feature_count"),
                                 "template_feature_count": evidence.get("keypoints_template"),
                                 "matched_features": data("matched_features"), "coordinates": None},
            "homography": {"inliers": data("homography_inliers"), "score": value("homography_score"),
                           "inlier_coordinates": None},
            "transform": {"matrix": evidence.get("transform_matrix"), "residual": value("transform_residual"),
                          "alignment_error": evidence.get("reprojection_error"),
                          "error_definition": "Recorded mean inlier reprojection error in pixels"},
            "acceptance": {"accepted": evidence.get("accepted"), "score": confidence,
                           "threshold": threshold,
                           "delta_to_threshold": confidence - threshold if confidence is not None and threshold is not None else None,
                           "policy": data("policy"), "reason": finished.get("reason")},
            "first_failing_stage": failure["stage"] if failure else None,
            "first_failing_stage_status": "RECORDED" if failure else (
                "NOT_APPLICABLE" if finished.get("status") == "SUCCESS" else "UNAVAILABLE"),
            "raw_evidence": evidence or None, "missing_events": trace.get("missing_events", []),
        })
    return {"report_type": "RegistrationReport", "document_id": document.get("document_id"),
            "attempt_count": len(attempts), "attempts": attempts,
            "notes": ["Source: RegistrationTrace events only. No history is reconstructed.",
                      "Missing trace or stage events remain unavailable."]}


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
