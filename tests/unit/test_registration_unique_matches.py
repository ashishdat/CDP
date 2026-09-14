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
