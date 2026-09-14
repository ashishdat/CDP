"""Render recorded template evidence; never execute matching or select a template."""

import json
from collections import defaultdict
from html import escape
from pathlib import Path

from workers.page_detection.router import (
    ALIGNMENT_CONFIDENT_THRESHOLD,
    ANCHOR_CONFIDENT_THRESHOLD,
    GRID_CONFIDENT_THRESHOLD,
)

THRESHOLDS = {"anchors": ANCHOR_CONFIDENT_THRESHOLD, "features": GRID_CONFIDENT_THRESHOLD,
              "registration": ALIGNMENT_CONFIDENT_THRESHOLD}


def build_report(document):
    selection = document.get("template_selection") or {}
    candidates = selection.get("candidate_templates", [])
    rows = []
    near = defaultdict(list)
    for candidate in candidates:
        scores = candidate.get("scores", {})
        diagnostic = candidate.get("diagnostics", {})
        thresholds = diagnostic.get("thresholds", THRESHOLDS)
        observed = {stage: value for stage, value in scores.items()
                    if stage in thresholds and value is not None}
        deltas = {stage: value - thresholds[stage] for stage, value in observed.items()}
        ratios = {stage: value / thresholds[stage] for stage, value in observed.items()}
        best = max(ratios, key=ratios.get) if ratios else None
        selected = (selection.get("template_id") == candidate["template_id"]
                    and selection.get("template_version") == candidate.get("template_version")
                    and selection.get("page_number") == candidate.get("page_number"))
        reasons = list(candidate.get("reasons", []))
        failures = []
        if selection.get("reason") == "AMBIGUOUS_TEMPLATE":
            failures.append("Ambiguity")
            reasons.append("AMBIGUOUS_TEMPLATE")
        if diagnostic.get("missing_required_anchors"):
            failures.append("Anchor")
            reasons.append("REQUIRED_ANCHORS_MISSING")
        for stage, label in (("anchors", "Anchor"), ("features", "Feature"),
                             ("registration", "Registration")):
            if stage in deltas and deltas[stage] < 0:
                failures.extend([label, "Threshold"])
                reasons.append(stage.upper() + "_BELOW_THRESHOLD")
        evidence = diagnostic.get("registration_evidence") or {}
        if evidence.get("rejection_reason"):
            reasons.append(evidence["rejection_reason"])
        if diagnostic.get("registration_gates_passed") is False:
            failures.append("Registration")
            if evidence.get("corner_validity") is False or evidence.get("algorithm") == "sift_flann_ransac":
                failures.append("Homography")
        if "REFERENCE_TEMPLATE_IMAGE_UNAVAILABLE" in reasons:
            failures.append("Feature")
        row = {
            "template_id": candidate["template_id"],
            "template_version": candidate.get("template_version"),
            "page_number": candidate.get("page_number"), "selected": selected,
            "anchor_score": scores.get("anchors"), "feature_score": scores.get("features"),
            "registration_score": scores.get("registration"),
            "overall_score": ratios[best] if best else None, "best_stage": best,
            "anchor_count": diagnostic.get("anchor_count"),
            "matched_anchor_count": diagnostic.get("matched_anchor_count"),
            "matched_features": diagnostic.get("matched_features"),
            "homography_score": diagnostic.get("homography_score"),
            "threshold": dict(thresholds), "delta_to_threshold": deltas,
            "rejection_reason": list(dict.fromkeys(reasons)) if not selected else [],
            "failure_stages": list(dict.fromkeys(failures)) if not selected else [],
            "evidence_missing": [name for name in ("anchor_count", "matched_features", "homography_score")
                                 if diagnostic.get(name) is None],
            "threshold_source": "recorded" if "thresholds" in diagnostic else "current_unchanged_policy",
        }
        rows.append(row)
        # Diagnostic band only: never used by the selector. Require repeated
        # page observations and known passing non-score gates at that stage.
        if not selected and selection.get("reason") != "AMBIGUOUS_TEMPLATE":
            for stage, ratio in ratios.items():
                gates_known = (stage == "features" or
                               (stage == "anchors" and diagnostic.get("missing_required_anchors") == []) or
                               (stage == "registration" and diagnostic.get("registration_gates_passed") is True))
                if gates_known and 0.95 <= ratio < 1.0:
                    near[(candidate["template_id"], candidate.get("template_version"), stage)].append(row)
    consistent = [key for key, values in near.items()
                  if len({row["page_number"] for row in values}) >= 2]
    status = "NO_QUALIFIED_TEMPLATE"
    if selection.get("template_id"):
        status = "SELECTED"
    elif selection.get("reason") == "AMBIGUOUS_TEMPLATE":
        status = "AMBIGUOUS_TEMPLATE"
    elif not any("anchors" in item.get("scores", {}) for item in candidates):
        status = "DISCOVERY_FAILURE"
    elif len(consistent) == 1 and len({key[:2] for key in near}) == 1:
        status = "THRESHOLD_CANDIDATE"
    elif any(row["registration_score"] is not None for row in rows):
        status = "REGISTRATION_FAILURE"
    scored = [row for row in rows if row["overall_score"] is not None]
    highest = max((row["overall_score"] for row in scored), default=None)
    leaders = [row for row in scored if row["overall_score"] == highest]
    return {
        "report_type": "TemplateDiscoveryReport", "document_id": document.get("document_id"),
        "status": status, "selection_reason": selection.get("reason"),
        "templates_considered": len({(row["template_id"], row["template_version"]) for row in rows}),
        "candidate_page_pairs": len(rows), "candidate_templates": rows,
        "highest_scoring_candidates": leaders,
        "overall_score_definition": "Maximum observed stage score / that stage threshold; diagnostic only, not selection confidence",
        "threshold_candidate_definition": "Exactly one template within 5% below the same stage threshold on at least two distinct pages, with known passing non-score gates and no competing near-threshold template",
        "notes": ["Null means unrecorded or unexecuted, not zero.",
                  "Historical reports cannot recover missing feature counts or homography evidence without rerunning matching.",
                  "No matching, OCR, threshold changes, or template selection performed by this report."],
    }


def write_report(document, directory):
    report = build_report(document)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2, allow_nan=False)
    (directory / "template_discovery.json").write_text(payload + "\n", encoding="utf-8")
    html = ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<title>Template discovery diagnostics</title><body><h1>Template discovery</h1>'
            f'<p>Status: {escape(report["status"])}</p>'
            f'<p>Templates considered: {report["templates_considered"]}; '
            f'page/template candidates: {report["candidate_page_pairs"]}</p>'
            '<p>Recorded evidence only. This report does not change selection.</p>'
            f'<pre>{escape(payload)}</pre></body></html>')
    (directory / "template_discovery.html").write_text(html, encoding="utf-8")
    return report
