import json

import cv2
import numpy as np
import pytest

from workers.page_detection.registration_coverage import (
    capture_inliers,
    capture_keypoints,
    capture_matches,
)
from workers.page_detection.registration_telemetry import ACTIVE, RegistrationTrace


@pytest.fixture(autouse=True)
def _verbose_registration_telemetry(monkeypatch):
    monkeypatch.setenv("CDP_REGISTRATION_VERBOSE_TELEMETRY", "1")


def test_capture_preserves_original_indices_and_duplicate_template_ids():
    image = [cv2.KeyPoint(1, 2, 1), cv2.KeyPoint(3, 4, 1)]
    template = [cv2.KeyPoint(10, 20, 1), cv2.KeyPoint(30, 40, 1)]
    descriptors = np.ones((2, 128), dtype=np.float32)
    first = cv2.DMatch(0, 0, 1.0)
    second = cv2.DMatch(1, 0, 2.0)
    pairs = [[first, cv2.DMatch(0, 1, 5.0)], [second, cv2.DMatch(1, 1, 8.0)]]
    trace = RegistrationTrace()
    token = ACTIVE.set(trace)
    try:
        capture_keypoints(image, descriptors, template, descriptors)
        capture_matches(pairs, [first, second])
        capture_inliers([first, second], np.array([True, True]), image, template)
    finally:
        ACTIVE.reset(token)
    keypoints = trace.events[0]["data"]["keypoints"]
    assert len(keypoints["image"][0]["descriptor_hash"]) == 64
    matches = trace.events[1]["data"]["matches"]
    assert len(matches) == 4
    assert sum(match["accepted"] for match in matches) == 2
    inliers = trace.events[2]["data"]["inliers"]
    assert [point["template_keypoint_id"] for point in inliers] == [0, 0]
    assert [point["image_keypoint_id"] for point in inliers] == [0, 1]
    assert len(inliers) == 2  # no deduplication
    json.dumps(trace.snapshot(), allow_nan=False)
