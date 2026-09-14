"""Registration-only feature images; original pixels and coordinate frames survive."""
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class PreprocessedRegistrationImage:
    image: np.ndarray
    to_original: np.ndarray
    metrics: dict

    def restore_keypoints(self, keypoints):
        """Restore locations only; descriptors describe the deskewed feature image."""
        for keypoint in keypoints:
            x, y = keypoint.pt
            point = self.to_original @ np.array([x, y, 1.0])
            keypoint.pt = (float(point[0]), float(point[1]))
        return keypoints


def preprocess_registration(image: np.ndarray) -> PreprocessedRegistrationImage:
    if image.ndim != 2 or image.dtype != np.uint8 or image.size == 0:
        raise ValueError("Expected a nonempty uint8 grayscale image")
    height, width = image.shape
    edges = cv2.Canny(image, 60, 180)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 1800, 60,
                            minLineLength=max(40, width // 8), maxLineGap=10)
    angles = []
    if lines is not None:
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
            angle = (angle + 45) % 90 - 45
            if abs(angle) <= 15:
                angles.append(angle)
    angle = float(np.median(angles)) if angles else 0.0
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    # Expand the canvas rather than clipping peripheral landmarks when deskewing.
    corners = np.array([[0, 0, 1], [width, 0, 1], [0, height, 1], [width, height, 1]]) @ matrix.T
    minimum = corners.min(axis=0)
    maximum = corners.max(axis=0)
    matrix[:, 2] -= minimum
    size = tuple(np.ceil(maximum - minimum).astype(int))
    deskewed = cv2.warpAffine(image, matrix, size, borderValue=255)
    ink = cv2.adaptiveThreshold(deskewed, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY_INV, 31, 15)
    h, w = ink.shape
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
                                  cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, w // 30), 1)))
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(25, h // 30))))
    rules = cv2.bitwise_or(horizontal, vertical)
    remainder = cv2.bitwise_and(ink, cv2.bitwise_not(rules))
    # Restore only rule pixels adjacent to surviving strokes, including text crossings.
    crossings = cv2.bitwise_and(rules, cv2.dilate(remainder, np.ones((5, 5), np.uint8)))
    retained = cv2.bitwise_or(remainder, crossings)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(retained, 8)
    suppressed = 0
    for label in range(1, count):
        _, _, cw, ch, area = stats[label]
        # Suppress large sparse frame remnants, never compact text or logos.
        if area > ink.size * .01 and cw * ch > ink.size * .1 and area / (cw * ch) < .15:
            suppressed += int(area)
            retained[labels == label] = 0
    return PreprocessedRegistrationImage(255 - retained, cv2.invertAffineTransform(matrix), {
        "deskew_degrees": angle,
        "line_pixels_removed": int(np.count_nonzero(rules & ~crossings)),
        "text_pixels_retained": int(np.count_nonzero(retained)),
        "text_pixels_retained_basis": "Foreground proxy, not OCR-confirmed text",
        "intersection_pixels_preserved": int(np.count_nonzero(crossings)),
        "large_component_pixels_removed": suppressed,
        "working_size": [w, h], "to_original": cv2.invertAffineTransform(matrix).tolist(),
    })
