import cv2

from workers.page_detection.template_alignment import _unique_template_matches


def test_31_image_points_mapping_to_one_template_retains_strongest():
    matches = [cv2.DMatch(index, 331, float(31 - index)) for index in range(31)]
    kept = _unique_template_matches(matches)
    assert kept == [matches[-1]]
    assert len(matches) - len(kept) == 30


def test_mixed_duplicates_retain_lowest_distance_per_template():
    matches = [cv2.DMatch(0, 7, 9.0), cv2.DMatch(1, 8, 2.0),
               cv2.DMatch(2, 7, 1.0), cv2.DMatch(3, 8, 5.0), cv2.DMatch(4, 9, 3.0)]
    assert _unique_template_matches(matches) == [matches[1], matches[2], matches[4]]


def test_already_unique_preserves_order_and_objects():
    matches = [cv2.DMatch(index, index, float(10 - index)) for index in range(5)]
    kept = _unique_template_matches(matches)
    assert all(left is right for left, right in zip(matches, kept, strict=True))


def test_equal_distance_keeps_first_and_empty_input_is_valid():
    first, second = cv2.DMatch(0, 7, 1.0), cv2.DMatch(1, 7, 1.0)
    assert _unique_template_matches([first, second]) == [first]
    assert _unique_template_matches([]) == []


def test_sift_orientations_at_same_physical_location_count_once():
    source = [cv2.KeyPoint(10, 20, 3), cv2.KeyPoint(10, 20, 3),
              cv2.KeyPoint(40, 50, 3), cv2.KeyPoint(70, 80, 3)]
    template = [cv2.KeyPoint(15, 25, 3), cv2.KeyPoint(15, 25, 3),
                cv2.KeyPoint(45, 55, 3), cv2.KeyPoint(75, 85, 3)]
    matches = [cv2.DMatch(0, 0, 9.0), cv2.DMatch(1, 1, 1.0),
               cv2.DMatch(2, 1, 2.0), cv2.DMatch(3, 3, 3.0)]
    assert _unique_template_matches(matches, source, template) == [matches[1], matches[3]]


def test_homography_policy_rejects_unsafe_geometry_and_accepts_exact_fit():
    import numpy as np

    from workers.page_detection.template_alignment import (
        RegistrationPolicy,
        _homography_passes_policy,
    )
    image = np.zeros((100, 100), dtype=np.uint8)
    points = np.float32([(x, y) for x in (5, 50, 95) for y in (5, 50, 95)]).reshape(-1, 1, 2)
    mask = np.ones((len(points), 1), dtype=np.uint8)
    policy = RegistrationPolicy()
    assert _homography_passes_policy(np.eye(3), mask, points, points, image, image, policy)
    unsafe = np.array([[0, -1, 99], [1, 0, 0], [0, 0, 1]], dtype=float)
    target = cv2.perspectiveTransform(points, unsafe)
    assert not _homography_passes_policy(unsafe, mask, points, target, image, image, policy)
    singular = np.eye(3)
    singular[2, 2] = 0
    assert not _homography_passes_policy(singular, mask, points, points, image, image, policy)


def test_ransac_prefers_safe_fit_over_more_inliers_and_scores_zero_error(monkeypatch):
    import numpy as np

    from workers.page_detection.template_alignment import RegistrationPolicy, _sift_alignment

    image = np.random.default_rng(42).integers(0, 256, (300, 300), dtype=np.uint8)
    calls = []

    def homography(src, dst, *args, **kwargs):
        calls.append(len(src))
        mask = np.ones((len(src), 1), dtype=np.uint8)
        if len(calls) == 1:
            return np.array([[0, -1, 299], [1, 0, 0], [0, 0, 1]], dtype=float), mask
        mask[-1] = 0
        return np.eye(3), mask

    monkeypatch.setattr(cv2, "findHomography", homography)
    result = _sift_alignment(image, image, RegistrationPolicy())
    assert len(calls) == 7
    assert result.accepted
    assert np.array_equal(result.homography, np.eye(3))
    assert result.reprojection_error == 0.0
    assert result.alignment_score > 0.98


def test_failed_primary_gets_two_bounded_feature_retries(monkeypatch):
    import numpy as np
    from PIL import Image

    import workers.page_detection.template_alignment as alignment

    policies = []
    rejected = alignment._failure("synthetic", "insufficient_inliers")

    def sift(candidate, reference, policy):
        policies.append(policy)
        return rejected

    monkeypatch.setattr(alignment, "_cheap_alignment", lambda *args: rejected)
    monkeypatch.setattr(alignment, "_sift_alignment", sift)
    image = Image.fromarray(np.full((100, 100), 255, dtype=np.uint8))
    alignment.align_to_reference(image, image, enforce_compatibility_precheck=False)
    assert [p.sift_features for p in policies] == [3000, 6000, 12000]
    baseline = {k: v for k, v in policies[0].__dict__.items() if k != "sift_features"}
    assert all({k: v for k, v in policy.__dict__.items() if k != "sift_features"} == baseline
               for policy in policies[1:])
