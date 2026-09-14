"""Observe pre-homography inputs and explain saved coverage; no matching runs here."""

import hashlib
import json
from html import escape
from pathlib import Path

import numpy as np

from workers.page_detection.registration_telemetry import ACTIVE


def observe(stage, candidate, reference, **details):
    trace = ACTIVE.get()
    if trace is None:
        return
    try:
        def image_info(image):
            array = np.asarray(image)
            height, width = array.shape[:2]
            digest = hashlib.sha256()
            digest.update(str((array.shape, str(array.dtype))).encode())
            digest.update(array.tobytes())
            return {"size": [width, height], "roi": [0, 0, width, height],
                    "image_hash": digest.hexdigest(), "roi_hash": digest.hexdigest(),
                    "hash_basis": "shape, dtype and decoded pixels; full-frame ROI",
                    "coverage_denominator": width * height}
        trace.emit(trace.current or "Registration Started", "OBSERVED", coverage_observation={
            "stage": stage, "source": image_info(candidate), "reference": image_info(reference),
            "feature_detector": "SIFT", "feature_descriptor": "SIFT float32",
            "matcher": "FLANN KD-tree, trees=5, checks=64, knn k=2",
            "ransac_inputs": None, "coverage_numerator": None,
            "coverage_formula": "min(area(convexHull(source_inliers))/(source_width*source_height), area(convexHull(template_inliers))/(template_width*template_height))",
            "note": "Coverage numerator requires inliers; unavailable before homography. No new coverage calculation is run.",
            **details,
        })
    except Exception:  # noqa: BLE001, S110 -- observations must not change registration
        pass


def write_saved_report(source_path, directory):
    document = json.loads(Path(source_path).read_text(encoding="utf-8"))
    attempts = []
    for candidate in document["template_selection"]["candidate_templates"]:
        diagnostic = candidate.get("diagnostics", {})
        evidence = diagnostic.get("registration_evidence")
        if not evidence:
            continue
        page = document["pages"][candidate["page_number"] - 1]
        executed = evidence.get("algorithm") == "sift_flann_ransac_homography"
        configured = (diagnostic.get("registration_policy") or {}).get("sift_features")
        pairs = evidence.get("candidate_match_count") if executed else None
        good = evidence.get("good_matches") if executed else None
        template_coverage = evidence.get("template_coverage")
        stages = [
            {"stage": "Expected Features", "value": configured, "reason": "Configured SIFT feature budget, not a guaranteed detection count"},
            {"stage": "Detected", "value": evidence.get("keypoints_source") if executed else None, "reason": "Recorded source keypoints"},
            {"stage": "Matched", "value": pairs, "reason": "KNN candidate lists; not yet accepted correspondences"},
            {"stage": "Filtered", "value": good, "removed": pairs - good if pairs is not None and good is not None else None,
             "reason": "Combined two-neighbor requirement and Lowe ratio filter; historical rejection counts were not separated"},
            {"stage": "Inliers (historical)", "value": evidence.get("inlier_count") if executed else None,
             "reason": "Previously recorded RANSAC result only; not rerun"},
            {"stage": "Coverage", "value": evidence.get("coverage_ratio"), "reason": "Minimum normalized inlier hull area, not feature retention ratio"},
        ]
        for stage in stages:
            stage.update(image_hash=None, roi_hash=None, feature_detector="SIFT" if executed else None,
                         feature_descriptor="SIFT" if executed else None, matcher="FLANN" if executed else None,
                         ransac_inputs=None)
        attempts.append({"template_id": candidate["template_id"], "page": candidate["page_number"],
            "input_image_size": [page["width"], page["height"]],
            "working_image_size": [page["width"], page["height"]] if executed else None,
            "roi": [0, 0, page["width"], page["height"]] if executed else None,
            "size_provenance": "Recorded document dimensions; source SIFT path uses full-size grayscale without resizing",
            "expected_feature_count": configured, "detected_feature_count": evidence.get("keypoints_source") if executed else None,
            "template_feature_count": evidence.get("keypoints_template") if executed else None,
            "candidate_feature_count": pairs, "matched_feature_count": pairs, "filtered_match_count": good,
            "coverage_numerator": {"source": None, "template": 0.0 if template_coverage == 0 and executed else None},
            "numerator_provenance": "Template zero follows from recorded zero normalized area with a positive image area; original hull coordinates were not retained",
            "coverage_denominator": {"source": page["width"] * page["height"], "template": None},
            "coverage_formula": "min(source_inlier_hull_area/source_image_area, template_inlier_hull_area/template_image_area)",
            "template_coverage": template_coverage, "coverage": evidence.get("coverage_ratio"),
            "waterfall": stages,
            "root_cause": ("Zero-area template inlier hull despite nonzero detected features and inliers. Exact duplicate/collinear correspondence cause is unavailable without retained points."
                           if template_coverage == 0 and executed else evidence.get("rejection_reason")),
            "hypotheses_not_proven": ["Duplicate template correspondences", "Collinear template inliers", "Wrong page or template", "ROI or preprocessing mismatch"],
            "missing_evidence": ["Historical pixel/ROI hashes", "Keypoint coordinates", "Match indices and distances", "Inlier mask", "RANSAC point arrays"],
        })
    report = {"source": str(source_path), "provenance": "Saved evidence; no retry or homography execution",
              "attempts": attempts, "notes": ["Missing values are not zero.", "No independent distance or spatial filter exists before RANSAC in this path."]}
    payload = json.dumps(report, indent=2, allow_nan=False)
    directory = Path(directory)
    (directory / "registration_coverage.json").write_text(payload + "\n", encoding="utf-8")
    charts = []
    for attempt in attempts:
        charts.append(f'<h2>{escape(attempt["template_id"])} page {attempt["page"]}</h2>')
        for step in attempt["waterfall"]:
            value = step["value"]
            width = min(100, max(0, value / (attempt["expected_feature_count"] or 1) * 100)) if value is not None else 0
            charts.append(f'<p>↓ {escape(step["stage"])}: {value if value is not None else "Unavailable"}</p>')
            if step["stage"] != "Coverage":
                charts.append(f'<div style="width:{width}%;height:16px;background:#168aad"></div>')
            charts.append(f'<p>{escape(step["reason"])}</p>')
    (directory / "registration_coverage.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Registration coverage</title>'
        '<body><h1>Coverage investigation</h1><p>Historical waterfall; coverage is an area fraction, not a count.</p>'
        + ''.join(charts) + '<pre>' + escape(payload) + '</pre></body></html>', encoding="utf-8")
    return report


def capture_keypoints(image_points, image_descriptors, template_points, template_descriptors):
    trace = ACTIVE.get()
    if trace is None:
        return
    def records(points, descriptors):
        return [{"keypoint_id": index, "x": float(point.pt[0]), "y": float(point.pt[1]),
                 "descriptor_hash": hashlib.sha256(descriptors[index].tobytes()).hexdigest()
                 if descriptors is not None else None}
                for index, point in enumerate(points)]
    trace.emit("Feature Matching", "OBSERVED", keypoints={
        "image": records(image_points, image_descriptors),
        "template": records(template_points, template_descriptors)})


def capture_matches(pairs, good, *, ratio_passed=None):
    trace = ACTIVE.get()
    if trace is None:
        return
    accepted = {id(match) for match in good}
    ratio_accepted = {id(match) for match in ratio_passed} if ratio_passed is not None else accepted
    records = []
    for pair_id, pair in enumerate(pairs):
        for rank, match in enumerate(pair):
            keep = id(match) in accepted
            reason = None if keep else ("SECOND_NEIGHBOR_COMPARATOR" if rank else
                                        "FEWER_THAN_TWO_NEIGHBORS" if len(pair) != 2 else
                                        "DUPLICATE_TEMPLATE_KEYPOINT" if id(match) in ratio_accepted else "RATIO_TEST_REJECTION")
            records.append({"match_id": f"{pair_id}:{rank}", "template_keypoint_id": match.trainIdx,
                            "image_keypoint_id": match.queryIdx, "distance": float(match.distance),
                            "accepted": keep, "rejected_reason": reason})
    trace.emit("Feature Matching", "OBSERVED", matches=records)


def capture_inliers(good, inliers, image_points, template_points):
    trace = ACTIVE.get()
    if trace is None:
        return
    records = []
    for index, (match, inlier) in enumerate(zip(good, inliers, strict=True)):
        if inlier:
            image_xy = image_points[match.queryIdx].pt
            template_xy = template_points[match.trainIdx].pt
            records.append({"filtered_match_index": index,
                            "template_keypoint_id": match.trainIdx, "image_keypoint_id": match.queryIdx,
                            "template_x": float(template_xy[0]), "template_y": float(template_xy[1]),
                            "image_x": float(image_xy[0]), "image_y": float(image_xy[1]),
                            "distance": float(match.distance)})
    trace.emit("Homography", "OBSERVED", inliers=records, inlier_mask=inliers.tolist())
