"""Adaptive registration: cheap edge alignment, then SIFT/FLANN/RANSAC."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, degrees, sqrt
from time import perf_counter
from typing import Any

import cv2
import numpy as np
from PIL import Image

from packages.domain.registration import RegistrationEvidence
from workers.page_detection import registration_telemetry as telemetry
from workers.page_detection.registration_coverage import (
    capture_inliers,
    capture_keypoints,
    capture_matches,
)
from workers.page_detection.registration_coverage import (
    observe as observe_coverage,
)
from workers.page_detection.registration_safety import record as record_safety
from workers.page_detection.registration_preprocessing import preprocess_registration
from workers.page_detection.template_compatibility import (
    TemplateCompatibilityEvidence,
    TemplateCompatibilityStatus,
    assess_template_compatibility,
)


@dataclass(frozen=True)
class RegistrationPolicy:
    lowe_ratio: float = 0.72
    ransac_reprojection_threshold: float = 4.0
    min_good_matches: int = 12
    min_inliers: int = 8
    # Variable claim text creates many legitimate Lowe-filtered outliers.
    # This floor is therefore paired with inlier-count, reprojection and
    # page-coverage gates; the ratio is never an acceptance signal alone.
    min_inlier_ratio: float = 0.12
    max_reprojection_error: float = 5.0
    min_coverage_ratio: float = 0.12
    cheap_min_confidence: float = 0.92
    cheap_max_aspect_delta: float = 0.015
    sift_features: int = 3000
    min_scale: float = 0.65
    max_scale: float = 1.55
    max_abs_rotation_degrees: float = 8.0
    # Dimensionless projective edge displacement after normalizing H[2,2].
    # Ordinary scanner keystone stays below ~0.02; degenerate homographies
    # observed on wrong-form matches are orders of magnitude larger.
    max_perspective_distortion: float = 0.02


DEFAULT_REGISTRATION_POLICY = RegistrationPolicy()


@dataclass(frozen=True)
class AlignmentResult:
    success: bool
    alignment_score: float
    good_match_count: int
    homography: np.ndarray | None
    warped: Image.Image | None
    method: str
    inlier_ratio: float = 0.0
    reprojection_error: float | None = None
    accepted: bool = False
    evidence: RegistrationEvidence | None = None
    compatibility: TemplateCompatibilityEvidence | None = None
    cheap_evidence: RegistrationEvidence | None = None
    sift_attempted: bool = False


def _gray(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("L"), dtype=np.uint8)


def _failure(method: str, reason: str, elapsed_ms: float = 0.0, **values) -> AlignmentResult:
    evidence = RegistrationEvidence(
        algorithm=method,
        accepted=False,
        rejection_reason=reason,
        processing_time_ms=elapsed_ms,
        **values,
    )
    telemetry.failed(reason, evidence=evidence.model_dump(mode="json"))
    return AlignmentResult(
        False,
        0.0,
        evidence.good_matches,
        None,
        None,
        method,
        evidence.inlier_ratio,
        evidence.reprojection_error,
        False,
        evidence,
    )


def _cheap_alignment(
    candidate: np.ndarray, reference: np.ndarray, policy: RegistrationPolicy
) -> AlignmentResult:
    started = perf_counter()
    telemetry.stage("Feature Matching", algorithm="edge_phase_correlation")
    ch, cw = candidate.shape
    rh, rw = reference.shape
    aspect_delta = abs((cw / ch) - (rw / rh)) / (rw / rh)
    record_safety("Aspect ratio", aspect_delta, {"max": policy.cheap_max_aspect_delta}, not aspect_delta > policy.cheap_max_aspect_delta, inputs={"source_dimensions": [cw, ch], "reference_dimensions": [rw, rh]})
    if aspect_delta > policy.cheap_max_aspect_delta:
        return _failure(
            "edge_phase_correlation", "aspect_ratio_mismatch", (perf_counter() - started) * 1000
        )
    resized = cv2.resize(candidate, (rw, rh), interpolation=cv2.INTER_AREA)
    cand_edges = cv2.Canny(resized, 60, 180).astype(np.float32)
    ref_edges = cv2.Canny(reference, 60, 180).astype(np.float32)
    if np.count_nonzero(cand_edges) < 50 or np.count_nonzero(ref_edges) < 50:
        return _failure(
            "edge_phase_correlation",
            "insufficient_edge_structure",
            (perf_counter() - started) * 1000,
        )
    (dx, dy), response = cv2.phaseCorrelate(cand_edges, ref_edges)
    confidence = float(np.clip(response, 0.0, 1.0))
    telemetry.stage("Acceptance", algorithm="edge_phase_correlation", threshold=policy.cheap_min_confidence)
    telemetry.measurements(confidence=confidence)
    record_safety("Cheap alignment confidence", confidence, {"min": policy.cheap_min_confidence}, not confidence < policy.cheap_min_confidence)
    if confidence < policy.cheap_min_confidence:
        return _failure(
            "edge_phase_correlation",
            "cheap_confidence_below_threshold",
            (perf_counter() - started) * 1000,
            alignment_confidence=confidence,
        )
    telemetry.stage("Transform", algorithm="edge_phase_correlation")
    matrix = np.array([[rw / cw, 0.0, dx], [0.0, rh / ch, dy], [0.0, 0.0, 1.0]])
    warped = cv2.warpPerspective(candidate, matrix, (rw, rh), borderValue=255)
    evidence = RegistrationEvidence(
        algorithm="edge_phase_correlation",
        alignment_confidence=confidence,
        coverage_ratio=1.0,
        template_coverage=1.0,
        scale_change=sqrt(abs(np.linalg.det(matrix[:2, :2]))),
        rotation_degrees=0.0,
        perspective_distortion=0.0,
        corner_validity=True,
        transform_matrix=matrix.tolist(),
        accepted=True,
        processing_time_ms=(perf_counter() - started) * 1000,
    )
    return AlignmentResult(
        True,
        confidence,
        0,
        matrix,
        Image.fromarray(warped),
        evidence.algorithm,
        accepted=True,
        evidence=evidence,
    )


def _unique_template_matches(matches):
    """Keep minimum descriptor distance per template ID; retain input order.

    Equal-distance ties keep the first observed match. The KNN ratio filter
    already supplies at most one candidate per image keypoint.
    """
    best = {}
    for match in matches:
        previous = best.get(match.trainIdx)
        if previous is None or match.distance < previous.distance:
            best[match.trainIdx] = match
    return [match for match in matches if best[match.trainIdx] is match]


def _sift_alignment(
    candidate: np.ndarray, reference: np.ndarray, policy: RegistrationPolicy
) -> AlignmentResult:
    started = perf_counter()
    telemetry.stage("Feature Matching", algorithm="sift_flann_ransac_homography")
    sift = cv2.SIFT_create(nfeatures=policy.sift_features)
    before_source = len(sift.detect(candidate, None))
    before_template = len(sift.detect(reference, None))
    source_features = preprocess_registration(candidate)
    template_features = preprocess_registration(reference)
    kp_source, desc_source = sift.detectAndCompute(source_features.image, None)
    kp_template, desc_template = sift.detectAndCompute(template_features.image, None)
    observe_coverage("Registration preprocessing", source_features.image, template_features.image,
                     source_preprocessing={**source_features.metrics, "feature_count_before": before_source,
                                           "feature_count_after": len(kp_source)},
                     template_preprocessing={**template_features.metrics, "feature_count_before": before_template,
                                             "feature_count_after": len(kp_template)})
    kp_source = source_features.restore_keypoints(kp_source)
    kp_template = template_features.restore_keypoints(kp_template)
    observe_coverage("Detected", candidate, reference, detected_feature_count=len(kp_source),
                     template_feature_count=len(kp_template),
                     source_descriptor_shape=list(desc_source.shape) if desc_source is not None else None,
                     template_descriptor_shape=list(desc_template.shape) if desc_template is not None else None,
                     reason="No descriptors" if desc_source is None or desc_template is None else "Descriptors available")
    capture_keypoints(kp_source, desc_source, kp_template, desc_template)
    telemetry.measurements(feature_count=len(kp_source))
    common = {
        "keypoints_source": len(kp_source),
        "keypoints_template": len(kp_template),
    }
    if desc_source is None or desc_template is None or len(kp_source) < 4:
        return _failure(
            "sift_flann_ransac_homography",
            "insufficient_keypoints",
            (perf_counter() - started) * 1000,
            **common,
        )
    matcher = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 5}, {"checks": 64})
    pairs = matcher.knnMatch(desc_source, desc_template, k=2)
    good = [
        pair[0]
        for pair in pairs
        if len(pair) == 2 and pair[0].distance < policy.lowe_ratio * pair[1].distance
    ]
    observe_coverage("Matched and filtered", candidate, reference,
                     candidate_feature_count=len(pairs), matched_feature_count=len(pairs), filtered_match_count=len(good),
                     unique_template_features=len({match.trainIdx for match in good}),
                     reductions={"fewer_than_two_neighbors": sum(len(pair) != 2 for pair in pairs),
                                 "ratio_test_rejection": sum(len(pair) == 2 and not pair[0].distance < policy.lowe_ratio * pair[1].distance for pair in pairs),
                                 "distance_rejection": "NOT_APPLIED", "spatial_rejection": "NOT_APPLIED"},
                     ratio_threshold=policy.lowe_ratio)
    ratio_passed = good
    good = _unique_template_matches(ratio_passed)
    observe_coverage("One-to-one template correspondences", candidate, reference,
                     template_matches_before=len(ratio_passed), template_matches_after=len(good),
                     duplicates_removed=len(ratio_passed) - len(good),
                     unique_template_points=len({match.trainIdx for match in good}),
                     unique_template_points_basis="Keypoint IDs; distinct IDs may share coordinates")
    capture_matches(pairs, good, ratio_passed=ratio_passed)
    common.update(candidate_match_count=len(pairs), good_matches=len(good))
    if len(good) < policy.min_good_matches:
        return _failure(
            "sift_flann_ransac_homography",
            "insufficient_good_matches",
            (perf_counter() - started) * 1000,
            **common,
        )
    src = np.float32([kp_source[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp_template[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    observe_coverage("RANSAC inputs ready", candidate, reference,
                     ransac_inputs={"source_points": src.tolist(), "template_points": dst.tolist(),
                                    "reprojection_threshold": policy.ransac_reprojection_threshold},
                     reason="Inputs captured after one-to-one template filtering, before existing homography call")
    telemetry.stage("Homography", matched_features=len(good))
    matrix, mask = cv2.findHomography(src, dst, cv2.RANSAC, policy.ransac_reprojection_threshold)
    if matrix is None or mask is None:
        return _failure(
            "sift_flann_ransac_homography",
            "homography_not_found",
            (perf_counter() - started) * 1000,
            **common,
        )
    inliers = mask.ravel().astype(bool)
    capture_inliers(good, inliers, kp_source, kp_template)
    inlier_count = int(inliers.sum())
    inlier_ratio = inlier_count / len(good)
    telemetry.stage("Transform", homography_inliers=inlier_count, transform_matrix=matrix.tolist())
    projected = cv2.perspectiveTransform(src, matrix)
    errors = np.linalg.norm(projected[inliers] - dst[inliers], axis=2).ravel()
    reprojection_error = float(errors.mean()) if errors.size else None
    source_hull = cv2.convexHull(src[inliers]) if inlier_count >= 3 else None
    template_hull = cv2.convexHull(dst[inliers]) if inlier_count >= 3 else None
    source_coverage = (
        float(cv2.contourArea(source_hull)) / (candidate.shape[0] * candidate.shape[1])
        if source_hull is not None
        else 0.0
    )
    template_coverage = (
        float(cv2.contourArea(template_hull)) / (reference.shape[0] * reference.shape[1])
        if template_hull is not None
        else 0.0
    )
    coverage = min(source_coverage, template_coverage)
    normalized = matrix / matrix[2, 2]
    scale_change = sqrt(abs(float(np.linalg.det(normalized[:2, :2]))))
    rotation_degrees = degrees(atan2(float(normalized[1, 0]), float(normalized[0, 0])))
    perspective_distortion = float(
        np.linalg.norm(normalized[2, :2]) * max(candidate.shape[0], candidate.shape[1])
    )
    source_corners = np.float32(
        [[[0, 0]], [[candidate.shape[1] - 1, 0]], [[candidate.shape[1] - 1, candidate.shape[0] - 1]], [[0, candidate.shape[0] - 1]]]
    )
    transformed_corners = cv2.perspectiveTransform(source_corners, matrix).reshape(-1, 2)
    margin_x, margin_y = reference.shape[1] * 0.1, reference.shape[0] * 0.1
    corner_validity = bool(
        np.isfinite(transformed_corners).all()
        and cv2.isContourConvex(transformed_corners.astype(np.float32))
        and np.all(transformed_corners[:, 0] >= -margin_x)
        and np.all(transformed_corners[:, 0] <= reference.shape[1] + margin_x)
        and np.all(transformed_corners[:, 1] >= -margin_y)
        and np.all(transformed_corners[:, 1] <= reference.shape[0] + margin_y)
    )
    confidence = float(
        np.clip(
            0.65 * inlier_ratio
            + 0.25 * min(1.0, coverage / 0.35)
            + 0.10 * max(0.0, 1.0 - (reprojection_error or 99.0) / policy.max_reprojection_error),
            0.0,
            1.0,
        )
    )
    telemetry.measurements(transform_residual=reprojection_error, homography_score=confidence)
    telemetry.stage("Acceptance", policy=policy.__dict__)
    telemetry.measurements(confidence=confidence, homography_score=confidence, transform_residual=reprojection_error)
    reasons: list[str] = []
    record_safety("Inlier count", inlier_count, {"min": policy.min_inliers}, not (inlier_count < policy.min_inliers))
    if inlier_count < policy.min_inliers:
        reasons.append("insufficient_inliers")
    record_safety("Inlier ratio", inlier_ratio, {"min": policy.min_inlier_ratio}, not (inlier_ratio < policy.min_inlier_ratio))
    if inlier_ratio < policy.min_inlier_ratio:
        reasons.append("low_inlier_ratio")
    record_safety("Residual", reprojection_error, {"max": policy.max_reprojection_error}, not (reprojection_error is None or reprojection_error > policy.max_reprojection_error))
    if reprojection_error is None or reprojection_error > policy.max_reprojection_error:
        reasons.append("high_reprojection_error")
    record_safety("Coverage", coverage, {"min": policy.min_coverage_ratio}, not (coverage < policy.min_coverage_ratio))
    if coverage < policy.min_coverage_ratio:
        reasons.append("low_coverage")
    record_safety("Scale", scale_change, {"min": policy.min_scale, "max": policy.max_scale}, bool(policy.min_scale <= scale_change <= policy.max_scale))
    if not policy.min_scale <= scale_change <= policy.max_scale:
        reasons.append("unsafe_scale_change")
    record_safety("Rotation", abs(rotation_degrees), {"max": policy.max_abs_rotation_degrees}, not (abs(rotation_degrees) > policy.max_abs_rotation_degrees))
    if abs(rotation_degrees) > policy.max_abs_rotation_degrees:
        reasons.append("unsafe_rotation")
    record_safety("Perspective", perspective_distortion, {"max": policy.max_perspective_distortion}, not (perspective_distortion > policy.max_perspective_distortion))
    if perspective_distortion > policy.max_perspective_distortion:
        reasons.append("unsafe_perspective_distortion")
    record_safety("Transformed corners", corner_validity, {"equals": True}, bool(corner_validity))
    if not corner_validity:
        reasons.append("invalid_transformed_corners")
    record_safety("Transform determinant", float(np.linalg.det(normalized)), None, None,
                  inputs={"matrix": matrix.tolist(), "note": "No independent determinant gate"})
    record_safety("Translation", normalized[:2, 2].tolist(), None, None,
                  inputs={"note": "No independent translation gate; corner validity is enforced"})
    record_safety("Anchor spread", None, None, None,
                  inputs={"note": "Registration uses feature inliers, not anchor positions"})
    record_safety("Homography condition", None, None, None,
                  inputs={"note": "Condition number is not calculated or gated by registration"})
    accepted = not reasons
    evidence = RegistrationEvidence(
        algorithm="sift_flann_ransac_homography",
        **common,
        inlier_count=inlier_count,
        inlier_ratio=inlier_ratio,
        reprojection_error=reprojection_error,
        coverage_ratio=coverage,
        template_coverage=template_coverage,
        scale_change=scale_change,
        rotation_degrees=rotation_degrees,
        perspective_distortion=perspective_distortion,
        corner_validity=corner_validity,
        homography_quality=confidence,
        alignment_confidence=confidence,
        transform_matrix=matrix.tolist(),
        accepted=accepted,
        rejection_reason=",".join(reasons) or None,
        processing_time_ms=(perf_counter() - started) * 1000,
    )
    warped = cv2.warpPerspective(
        candidate, matrix, (reference.shape[1], reference.shape[0]), borderValue=255
    )
    return AlignmentResult(
        accepted,
        confidence,
        len(good),
        matrix,
        Image.fromarray(warped),
        evidence.algorithm,
        inlier_ratio,
        reprojection_error,
        accepted,
        evidence,
    )


def _sift_alignment_multiscale(
    candidate: np.ndarray,
    reference: np.ndarray,
    policy: RegistrationPolicy,
    *,
    scales: tuple[float, ...] = (0.85, 1.0, 1.15),
) -> AlignmentResult:
    """Try SIFT at multiple candidate scales; keep the best accepted or best near-miss."""
    from packages.recovery.registration_near_miss import assess_evidence_near_miss

    best: AlignmentResult | None = None
    best_key = (-1, -1, -1, -1.0)  # accepted, near_miss, inliers, ratio
    for scale in scales:
        if abs(scale - 1.0) < 1e-6:
            scaled = candidate
            result = _sift_alignment(scaled, reference, policy)
        else:
            scaled = cv2.resize(
                candidate,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR,
            )
            scaled_result = _sift_alignment(scaled, reference, policy)
            if scaled_result.homography is None:
                result = scaled_result
            else:
                # H_scaled maps scaled→template; compose so H maps original→template.
                s_forward = np.array(
                    [[scale, 0.0, 0.0], [0.0, scale, 0.0], [0.0, 0.0, 1.0]],
                    dtype=np.float64,
                )
                composed = scaled_result.homography @ s_forward
                warped = cv2.warpPerspective(
                    candidate,
                    composed,
                    (reference.shape[1], reference.shape[0]),
                    borderValue=255,
                )
                evidence = scaled_result.evidence
                if evidence is not None:
                    evidence = evidence.model_copy(
                        update={"transform_matrix": composed.tolist()}
                    )
                if scaled_result.warped is not None:
                    scaled_result.warped.close()
                result = AlignmentResult(
                    scaled_result.success,
                    scaled_result.alignment_score,
                    scaled_result.good_match_count,
                    composed,
                    Image.fromarray(warped),
                    scaled_result.method,
                    scaled_result.inlier_ratio,
                    scaled_result.reprojection_error,
                    scaled_result.accepted,
                    evidence,
                    scaled_result.compatibility,
                    scaled_result.cheap_evidence,
                    scaled_result.sift_attempted,
                )
        accepted_rank = 1 if result.accepted else 0
        inliers = int(result.evidence.inlier_count) if result.evidence else 0
        ratio = float(result.inlier_ratio or 0.0)
        near = (
            assess_evidence_near_miss(result.evidence).is_near_miss
            if result.evidence is not None
            else False
        )
        key = (accepted_rank, 1 if near else 0, inliers, ratio)
        if best is None or key > best_key:
            if best is not None and best.warped is not None and best.warped is not result.warped:
                best.warped.close()
            best = result
            best_key = key
            if result.accepted:
                break
        elif result.warped is not None:
            result.warped.close()
    assert best is not None
    return best


def align_near_miss_boosted(
    candidate: Image.Image,
    reference: Image.Image,
    *,
    family: str | None = None,
    base_policy: RegistrationPolicy | None = None,
) -> AlignmentResult:
    """Bounded secondary geometric pass for ratio-only near-miss failures.

    Raises sift_features and searches a small scale pyramid. Acceptance policy
    thresholds are unchanged — accept only if full gates pass.
    """
    base = base_policy or DEFAULT_REGISTRATION_POLICY
    boosted = RegistrationPolicy(
        lowe_ratio=base.lowe_ratio,
        ransac_reprojection_threshold=base.ransac_reprojection_threshold,
        min_good_matches=base.min_good_matches,
        min_inliers=base.min_inliers,
        min_inlier_ratio=base.min_inlier_ratio,
        max_reprojection_error=base.max_reprojection_error,
        min_coverage_ratio=base.min_coverage_ratio,
        cheap_min_confidence=base.cheap_min_confidence,
        cheap_max_aspect_delta=base.cheap_max_aspect_delta,
        sift_features=max(base.sift_features, 5000),
        min_scale=base.min_scale,
        max_scale=base.max_scale,
        max_abs_rotation_degrees=base.max_abs_rotation_degrees,
        max_perspective_distortion=base.max_perspective_distortion,
    )
    candidate_arr, reference_arr = _gray(candidate), _gray(reference)
    compatibility = assess_template_compatibility(candidate, reference, family=family)
    sift = _sift_alignment_multiscale(candidate_arr, reference_arr, boosted)
    evidence = sift.evidence
    if evidence is not None:
        evidence = evidence.model_copy(
            update={"algorithm": "sift_flann_ransac_homography_near_miss_boost"}
        )
    return AlignmentResult(
        sift.success,
        sift.alignment_score,
        sift.good_match_count,
        sift.homography,
        sift.warped,
        "sift_flann_ransac_homography_near_miss_boost",
        sift.inlier_ratio,
        sift.reprojection_error,
        sift.accepted,
        evidence,
        compatibility,
        sift.cheap_evidence,
        True,
    )


def _affine_then_homography(
    candidate: np.ndarray, reference: np.ndarray, policy: RegistrationPolicy
) -> AlignmentResult:
    """Affine-first coarse align, then full homography on the rectified crop.

    Targets mild phone keystone where direct projective fit overshoots the
    perspective gate. Final acceptance still uses unchanged homography gates.
    """
    started = perf_counter()
    # First get SIFT matches for affine.
    sift = cv2.SIFT_create(nfeatures=max(policy.sift_features, 4000))
    source_features = preprocess_registration(candidate)
    template_features = preprocess_registration(reference)
    kp_source, desc_source = sift.detectAndCompute(source_features.image, None)
    kp_template, desc_template = sift.detectAndCompute(template_features.image, None)
    kp_source = source_features.restore_keypoints(kp_source)
    kp_template = template_features.restore_keypoints(kp_template)
    if desc_source is None or desc_template is None or len(kp_source) < 4:
        return _failure(
            "affine_then_homography",
            "insufficient_keypoints",
            (perf_counter() - started) * 1000,
        )
    matcher = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 5}, {"checks": 64})
    pairs = matcher.knnMatch(desc_source, desc_template, k=2)
    good = [
        pair[0]
        for pair in pairs
        if len(pair) == 2 and pair[0].distance < policy.lowe_ratio * pair[1].distance
    ]
    good = _unique_template_matches(good)
    if len(good) < policy.min_good_matches:
        return _failure(
            "affine_then_homography",
            "insufficient_good_matches",
            (perf_counter() - started) * 1000,
            good_matches=len(good),
        )
    src = np.float32([kp_source[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp_template[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    affine, inlier_mask = cv2.estimateAffinePartial2D(
        src, dst, method=cv2.RANSAC, ransacReprojThreshold=policy.ransac_reprojection_threshold
    )
    if affine is None:
        return _failure(
            "affine_then_homography",
            "affine_not_found",
            (perf_counter() - started) * 1000,
            good_matches=len(good),
        )
    # Warp candidate by affine into reference-sized canvas, then full SIFT H.
    approx = cv2.warpAffine(
        candidate, affine, (reference.shape[1], reference.shape[0]), borderValue=255
    )
    # Identity-ish second stage: matches on already-affine-aligned page.
    second = _sift_alignment(approx, reference, policy)
    if second.homography is None:
        return second
    # Compose: x_ref = H2 * Affine * x_orig  (Affine as 3x3).
    affine_h = np.vstack([affine, np.array([0.0, 0.0, 1.0])])
    composed = second.homography @ affine_h
    warped = cv2.warpPerspective(
        candidate, composed, (reference.shape[1], reference.shape[0]), borderValue=255
    )
    evidence = second.evidence
    if evidence is not None:
        evidence = evidence.model_copy(
            update={
                "algorithm": "affine_then_homography",
                "transform_matrix": composed.tolist(),
                "processing_time_ms": (perf_counter() - started) * 1000,
            }
        )
    if second.warped is not None:
        second.warped.close()
    return AlignmentResult(
        second.success,
        second.alignment_score,
        second.good_match_count,
        composed,
        Image.fromarray(warped),
        "affine_then_homography",
        second.inlier_ratio,
        second.reprojection_error,
        second.accepted,
        evidence,
        second.compatibility,
        second.cheap_evidence,
        True,
    )


def align_perspective_recovery(
    candidate: Image.Image,
    reference: Image.Image,
    *,
    family: str | None = None,
    base_policy: RegistrationPolicy | None = None,
) -> AlignmentResult:
    """Mild-perspective recovery: boosted multi-scale SIFT, then affine-first."""
    base = base_policy or DEFAULT_REGISTRATION_POLICY
    boosted = RegistrationPolicy(
        lowe_ratio=base.lowe_ratio,
        ransac_reprojection_threshold=base.ransac_reprojection_threshold,
        min_good_matches=base.min_good_matches,
        min_inliers=base.min_inliers,
        min_inlier_ratio=base.min_inlier_ratio,
        max_reprojection_error=base.max_reprojection_error,
        min_coverage_ratio=base.min_coverage_ratio,
        cheap_min_confidence=base.cheap_min_confidence,
        cheap_max_aspect_delta=base.cheap_max_aspect_delta,
        sift_features=max(base.sift_features, 5000),
        min_scale=base.min_scale,
        max_scale=base.max_scale,
        max_abs_rotation_degrees=base.max_abs_rotation_degrees,
        max_perspective_distortion=base.max_perspective_distortion,
    )
    candidate_arr, reference_arr = _gray(candidate), _gray(reference)
    compatibility = assess_template_compatibility(candidate, reference, family=family)
    multi = _sift_alignment_multiscale(candidate_arr, reference_arr, boosted)
    if multi.accepted:
        evidence = multi.evidence
        if evidence is not None:
            evidence = evidence.model_copy(
                update={"algorithm": "sift_perspective_recovery_boost"}
            )
        return AlignmentResult(
            multi.success,
            multi.alignment_score,
            multi.good_match_count,
            multi.homography,
            multi.warped,
            "sift_perspective_recovery_boost",
            multi.inlier_ratio,
            multi.reprojection_error,
            multi.accepted,
            evidence,
            compatibility,
            multi.cheap_evidence,
            True,
        )
    affine = _affine_then_homography(candidate_arr, reference_arr, boosted)
    if multi.warped is not None and multi.warped is not affine.warped:
        multi.warped.close()
    return AlignmentResult(
        affine.success,
        affine.alignment_score,
        affine.good_match_count,
        affine.homography,
        affine.warped,
        affine.method,
        affine.inlier_ratio,
        affine.reprojection_error,
        affine.accepted,
        affine.evidence,
        compatibility,
        affine.cheap_evidence,
        True,
    )


def align_learned_matcher(
    candidate: Image.Image,
    reference: Image.Image,
    *,
    family: str | None = None,
    base_policy: RegistrationPolicy | None = None,
    extractor: Any | None = None,
) -> AlignmentResult:
    """Catastrophic residual: SuperPoint+LightGlue matches → same Acceptance gates."""
    from packages.recovery.learned_matcher import SuperPointLightGlueExtractor

    base = base_policy or DEFAULT_REGISTRATION_POLICY
    policy = RegistrationPolicy(
        lowe_ratio=base.lowe_ratio,
        ransac_reprojection_threshold=base.ransac_reprojection_threshold,
        min_good_matches=max(8, base.min_good_matches // 2),
        min_inliers=base.min_inliers,
        min_inlier_ratio=base.min_inlier_ratio,
        max_reprojection_error=base.max_reprojection_error,
        min_coverage_ratio=base.min_coverage_ratio,
        cheap_min_confidence=base.cheap_min_confidence,
        cheap_max_aspect_delta=base.cheap_max_aspect_delta,
        sift_features=base.sift_features,
        min_scale=base.min_scale,
        max_scale=base.max_scale,
        max_abs_rotation_degrees=base.max_abs_rotation_degrees,
        max_perspective_distortion=base.max_perspective_distortion,
    )
    candidate_arr, reference_arr = _gray(candidate), _gray(reference)
    compatibility = assess_template_compatibility(candidate, reference, family=family)
    started = perf_counter()
    matcher = extractor or SuperPointLightGlueExtractor()
    try:
        corr = matcher.extract(candidate, reference)
    except RuntimeError as exc:
        return AlignmentResult(
            **{
                **_failure(
                    "superpoint_lightglue_homography",
                    f"learned_matcher_unavailable:{type(exc).__name__}",
                    (perf_counter() - started) * 1000,
                ).__dict__,
                "compatibility": compatibility,
                "sift_attempted": True,
            }
        )
    if corr is None or len(corr.source_xy) < policy.min_good_matches:
        return AlignmentResult(
            **{
                **_failure(
                    "superpoint_lightglue_homography",
                    "insufficient_good_matches",
                    (perf_counter() - started) * 1000,
                    good_matches=0 if corr is None else len(corr.source_xy),
                ).__dict__,
                "compatibility": compatibility,
                "sift_attempted": True,
            }
        )
    src = corr.source_xy.reshape(-1, 1, 2).astype(np.float32)
    dst = corr.template_xy.reshape(-1, 1, 2).astype(np.float32)
    matrix, mask = cv2.findHomography(
        src, dst, cv2.RANSAC, policy.ransac_reprojection_threshold
    )
    if matrix is None or mask is None:
        return AlignmentResult(
            **{
                **_failure(
                    "superpoint_lightglue_homography",
                    "homography_not_found",
                    (perf_counter() - started) * 1000,
                    good_matches=len(corr.source_xy),
                ).__dict__,
                "compatibility": compatibility,
                "sift_attempted": True,
            }
        )
    inliers = mask.ravel().astype(bool)
    inlier_count = int(inliers.sum())
    good_count = int(len(corr.source_xy))
    inlier_ratio = inlier_count / max(1, good_count)
    projected = cv2.perspectiveTransform(src, matrix)
    errors = np.linalg.norm(projected[inliers] - dst[inliers], axis=2).ravel()
    reprojection_error = float(errors.mean()) if errors.size else None
    source_hull = cv2.convexHull(src[inliers]) if inlier_count >= 3 else None
    template_hull = cv2.convexHull(dst[inliers]) if inlier_count >= 3 else None
    source_coverage = (
        float(cv2.contourArea(source_hull)) / (candidate_arr.shape[0] * candidate_arr.shape[1])
        if source_hull is not None
        else 0.0
    )
    template_coverage = (
        float(cv2.contourArea(template_hull))
        / (reference_arr.shape[0] * reference_arr.shape[1])
        if template_hull is not None
        else 0.0
    )
    coverage = min(source_coverage, template_coverage)
    normalized = matrix / matrix[2, 2]
    scale_change = sqrt(abs(float(np.linalg.det(normalized[:2, :2]))))
    rotation_degrees = degrees(atan2(float(normalized[1, 0]), float(normalized[0, 0])))
    perspective_distortion = float(
        np.linalg.norm(normalized[2, :2])
        * max(candidate_arr.shape[0], candidate_arr.shape[1])
    )
    source_corners = np.float32(
        [
            [[0, 0]],
            [[candidate_arr.shape[1] - 1, 0]],
            [[candidate_arr.shape[1] - 1, candidate_arr.shape[0] - 1]],
            [[0, candidate_arr.shape[0] - 1]],
        ]
    )
    transformed_corners = cv2.perspectiveTransform(source_corners, matrix).reshape(-1, 2)
    margin_x, margin_y = reference_arr.shape[1] * 0.1, reference_arr.shape[0] * 0.1
    corner_validity = bool(
        np.isfinite(transformed_corners).all()
        and cv2.isContourConvex(transformed_corners.astype(np.float32))
        and np.all(transformed_corners[:, 0] >= -margin_x)
        and np.all(transformed_corners[:, 0] <= reference_arr.shape[1] + margin_x)
        and np.all(transformed_corners[:, 1] >= -margin_y)
        and np.all(transformed_corners[:, 1] <= reference_arr.shape[0] + margin_y)
    )
    confidence = float(
        np.clip(
            0.65 * inlier_ratio
            + 0.25 * min(1.0, coverage / 0.35)
            + 0.10
            * max(
                0.0,
                1.0 - (reprojection_error or 99.0) / policy.max_reprojection_error,
            ),
            0.0,
            1.0,
        )
    )
    reasons: list[str] = []
    if inlier_count < policy.min_inliers:
        reasons.append("insufficient_inliers")
    if inlier_ratio < policy.min_inlier_ratio:
        reasons.append("low_inlier_ratio")
    if reprojection_error is None or reprojection_error > policy.max_reprojection_error:
        reasons.append("high_reprojection_error")
    if coverage < policy.min_coverage_ratio:
        reasons.append("low_coverage")
    if not policy.min_scale <= scale_change <= policy.max_scale:
        reasons.append("unsafe_scale_change")
    if abs(rotation_degrees) > policy.max_abs_rotation_degrees:
        reasons.append("unsafe_rotation")
    if perspective_distortion > policy.max_perspective_distortion:
        reasons.append("unsafe_perspective_distortion")
    if not corner_validity:
        reasons.append("invalid_transformed_corners")
    accepted = not reasons
    evidence = RegistrationEvidence(
        algorithm="superpoint_lightglue_homography",
        good_matches=good_count,
        inlier_count=inlier_count,
        inlier_ratio=inlier_ratio,
        reprojection_error=reprojection_error,
        coverage_ratio=coverage,
        template_coverage=template_coverage,
        scale_change=scale_change,
        rotation_degrees=rotation_degrees,
        perspective_distortion=perspective_distortion,
        corner_validity=corner_validity,
        homography_quality=confidence,
        alignment_confidence=confidence,
        transform_matrix=matrix.tolist(),
        accepted=accepted,
        rejection_reason=",".join(reasons) or None,
        processing_time_ms=(perf_counter() - started) * 1000,
    )
    warped = cv2.warpPerspective(
        candidate_arr,
        matrix,
        (reference_arr.shape[1], reference_arr.shape[0]),
        borderValue=255,
    )
    return AlignmentResult(
        accepted,
        confidence,
        good_count,
        matrix,
        Image.fromarray(warped),
        evidence.algorithm,
        inlier_ratio,
        reprojection_error,
        accepted,
        evidence,
        compatibility,
        None,
        True,
    )


@telemetry.traced_registration
def align_to_reference(
    candidate: Image.Image,
    reference: Image.Image,
    policy: RegistrationPolicy | None = None,
    *,
    family: str | None = None,
    enforce_compatibility_precheck: bool = False,
    compatibility_evidence: TemplateCompatibilityEvidence | None = None,
) -> AlignmentResult:
    selected = policy or DEFAULT_REGISTRATION_POLICY
    observe_coverage("Input image", candidate, reference, preprocessing="Before grayscale conversion")
    candidate_arr, reference_arr = _gray(candidate), _gray(reference)
    compatibility = compatibility_evidence or assess_template_compatibility(
        candidate, reference, family=family
    )
    cheap = _cheap_alignment(candidate_arr, reference_arr, selected)
    if cheap.success:
        return AlignmentResult(
            **{
                **cheap.__dict__,
                "compatibility": compatibility,
                "cheap_evidence": cheap.evidence,
            }
        )
    if (
        enforce_compatibility_precheck
        and compatibility.status == TemplateCompatibilityStatus.INCOMPATIBLE
    ):
        telemetry.stage("Acceptance", algorithm="template_compatibility_precheck")
        rejected = _failure(
            "template_compatibility_precheck",
            "template_lineage_mismatch",
        )
        return AlignmentResult(
            **{
                **rejected.__dict__,
                "compatibility": compatibility,
                "cheap_evidence": cheap.evidence,
                "sift_attempted": False,
            }
        )
    sift = _sift_alignment(candidate_arr, reference_arr, selected)
    return AlignmentResult(
        **{
            **sift.__dict__,
            "compatibility": compatibility,
            "cheap_evidence": cheap.evidence,
            "sift_attempted": True,
        }
    )
