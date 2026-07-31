"""OpenCV feature-matching/homography alignment: warps an incoming scan
onto a reference template image so downstream regional OCR reads the same
pixel regions regardless of scan-to-scan skew, translation, or minor scale
differences.

Uses ORB (patent-free, no extra dependency beyond opencv) + a brute-force
Hamming matcher + RANSAC homography. `alignment_score` (the RANSAC inlier
ratio among the top matches) is one of the hybrid router's inputs
(docs/ARCHITECTURE.md §9) -- a low score means "this page's structure
doesn't match the template" and should route to the next escalation step,
not be forced through misaligned regional OCR.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

MIN_GOOD_MATCHES = 15
ORB_FEATURES = 2000
LOWE_RATIO = 0.75
MIN_ALIGNMENT_SCORE = 0.35
MAX_REPROJECTION_ERROR = 8.0


@dataclass(frozen=True)
class AlignmentResult:
    success: bool
    alignment_score: float  # RANSAC inlier ratio among good matches, in [0, 1]
    good_match_count: int
    homography: np.ndarray | None  # 3x3, candidate -> reference
    warped: Image.Image | None  # candidate image warped into reference's frame
    method: str = "orb_homography"
    inlier_ratio: float = 0.0
    reprojection_error: float | None = None
    accepted: bool = False


def _to_gray_array(image: Image.Image) -> np.ndarray:
    return np.array(image.convert("L"))


def align_to_reference(candidate: Image.Image, reference: Image.Image) -> AlignmentResult:
    candidate_arr = _to_gray_array(candidate)
    reference_arr = _to_gray_array(reference)

    orb = cv2.ORB_create(nfeatures=ORB_FEATURES)
    kp_candidate, desc_candidate = orb.detectAndCompute(candidate_arr, None)
    kp_reference, desc_reference = orb.detectAndCompute(reference_arr, None)

    if desc_candidate is None or desc_reference is None or len(kp_candidate) < 4:
        return AlignmentResult(
            success=False, alignment_score=0.0, good_match_count=0, homography=None, warped=None
        )

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    raw_matches = matcher.knnMatch(desc_candidate, desc_reference, k=2)
    good_matches = [
        m for m, n in raw_matches if len(raw_matches) and m.distance < LOWE_RATIO * n.distance
    ]

    if len(good_matches) < MIN_GOOD_MATCHES:
        return AlignmentResult(
            success=False,
            alignment_score=0.0,
            good_match_count=len(good_matches),
            homography=None,
            warped=None,
        )

    src_pts = np.float32([kp_candidate[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp_reference[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)

    homography, inlier_mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
    if homography is None:
        return AlignmentResult(
            success=False,
            alignment_score=0.0,
            good_match_count=len(good_matches),
            homography=None,
            warped=None,
        )

    inlier_ratio = float(inlier_mask.sum()) / len(good_matches)
    projected = cv2.perspectiveTransform(src_pts, homography)
    inliers = inlier_mask.ravel().astype(bool)
    errors = np.linalg.norm(projected[inliers] - dst_pts[inliers], axis=2).ravel()
    reprojection_error = float(errors.mean()) if len(errors) else None
    accepted = (
        inlier_ratio >= MIN_ALIGNMENT_SCORE
        and reprojection_error is not None
        and reprojection_error <= MAX_REPROJECTION_ERROR
    )
    height, width = reference_arr.shape
    warped_arr = cv2.warpPerspective(candidate_arr, homography, (width, height))

    return AlignmentResult(
        success=accepted,
        alignment_score=inlier_ratio,
        good_match_count=len(good_matches),
        homography=homography,
        warped=Image.fromarray(warped_arr),
        inlier_ratio=inlier_ratio,
        reprojection_error=reprojection_error,
        accepted=accepted,
    )
