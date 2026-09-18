import cv2
import numpy as np
import pytest

from workers.page_detection.registration_preprocessing import preprocess_registration


def test_blank_and_input_unchanged():
    image = np.full((100, 120), 255, np.uint8)
    before = image.copy()
    result = preprocess_registration(image)
    assert np.array_equal(image, before)
    assert np.all(result.image == 255)
    assert result.metrics['line_pixels_removed'] == 0


def test_rules_removed_crossings_and_landmark_preserved():
    image = np.full((400, 400), 255, np.uint8)
    cv2.line(image, (20, 200), (380, 200), 0, 2)
    cv2.line(image, (200, 20), (200, 380), 0, 2)
    cv2.putText(image, 'A', (90, 208), cv2.FONT_HERSHEY_SIMPLEX, .8, 0, 2)
    cv2.circle(image, (300, 100), 8, 0, -1)
    result = preprocess_registration(image)
    assert result.metrics['line_pixels_removed'] > 500
    assert result.metrics['intersection_pixels_preserved'] > 0
    assert np.count_nonzero(result.image[90:110, 290:310] < 128) > 100
    assert np.count_nonzero(result.image[180:215, 85:115] < 128) > 30


def test_deskew_coordinates_return_to_original():
    image = np.full((300, 400), 255, np.uint8)
    for y in (60, 120, 180, 240):
        cv2.line(image, (30, y), (360, y + 23), 0, 2)
    result = preprocess_registration(image)
    assert 3 < result.metrics['deskew_degrees'] < 5
    original = np.array([100., 120., 1.])
    forward = cv2.invertAffineTransform(result.to_original)
    working = forward @ original
    keypoint = cv2.KeyPoint(float(working[0]), float(working[1]), 5)
    restored = result.restore_keypoints([keypoint])[0]
    assert np.allclose(restored.pt, original[:2], atol=1e-4)


def test_large_sparse_component_suppressed():
    image = np.full((400, 400), 255, np.uint8)
    cv2.line(image, (30, 30), (370, 370), 0, 5)
    cv2.line(image, (370, 30), (30, 370), 0, 5)
    result = preprocess_registration(image)
    assert result.metrics['large_component_pixels_removed'] > 0


def test_invalid_input():
    with pytest.raises(ValueError):
        preprocess_registration(np.zeros((10, 10, 3), np.uint8))
