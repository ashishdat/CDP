import numpy as np
import pytest

from packages.geometry import (
    Box,
    align_local,
    connected_components,
    refine_roi,
    register,
    safe_cell,
    text_envelope,
    transform_box,
)

POINTS = ((0, 0), (20, 0), (0, 20), (20, 20))


def test_affine_registration_maps_all_corners_with_outward_rounding():
    source = tuple((2 * x + 0.25 * y + 5, 3 * y + 7) for x, y in POINTS)
    result = register(POINTS, source)
    assert result.accepted
    assert result.max_error < 1e-10
    assert transform_box(Box(1, 2, 5, 6), result) == Box(7, 13, 17, 25)


def test_rotation_registration_uses_four_corners():
    result = register(POINTS, tuple((40 - y, x + 10) for x, y in POINTS))
    assert result.accepted
    assert transform_box(Box(2, 4, 8, 12), result) == Box(28, 12, 36, 18)


@pytest.mark.parametrize(
    "source",
    [
        (),
        ((0, 0), (1, 1)),
        ((float("nan"), 0), (1, 0), (0, 1), (1, 1)),
        ((0, 0), (-20, 0), (0, 20), (-20, 20)),
        ((0, 0), (0, 0), (0, 0), (0, 0)),
        ((0, 0), (20, 0), (0, 20), (80, 80)),
    ],
)
def test_invalid_registration_never_exposes_transform(source):
    result = register(POINTS, source)
    assert not result.accepted
    assert result.matrix is None
    with pytest.raises(ValueError, match="Accepted"):
        transform_box(Box(0, 0, 2, 2), result)


def test_collinear_landmarks_are_rejected():
    assert (
        register(((0, 0), (1, 1), (2, 2)), ((0, 0), (2, 2), (4, 4))).reason
        == "DEGENERATE_LANDMARKS"
    )


@pytest.mark.parametrize("error", [-1, float("nan"), float("inf")])
def test_invalid_registration_policy(error):
    with pytest.raises(ValueError):
        register(POINTS, POINTS, max_error=error)


def test_safe_cell_clipping_inset_and_empty_intersection():
    assert safe_cell(Box(-3, -4, 12, 14), (10, 10)) == Box(0, 0, 10, 10)
    assert safe_cell(Box(2, 2, 8, 8), (10, 10), inset=1) == Box(3, 3, 7, 7)
    assert safe_cell(Box(20, 20, 30, 30), (10, 10)) is None
    assert safe_cell(Box(0, 0, 2, 2), (10, 10), inset=1) is None


def test_local_alignment_finds_translation_and_preserves_pixels():
    image = np.full((50, 60), 255, np.uint8)
    patch = np.full((8, 10), 255, np.uint8)
    patch[1:6, 2:4] = 0
    patch[5:7, 3:8] = 80
    image[17:25, 23:33] = patch
    before = image.copy()
    result = align_local(image, patch, Box(20, 15, 30, 23), Box(0, 0, 60, 50))
    assert result.accepted
    assert result.box == Box(23, 17, 33, 25)
    np.testing.assert_array_equal(image, before)


def test_local_alignment_cannot_select_structure_outside_safe_cell():
    image = np.full((20, 40), 255, np.uint8)
    patch = np.zeros((5, 5), np.uint8)
    patch[2, 2] = 255
    image[5:10, 25:30] = patch
    result = align_local(image, patch, Box(5, 5, 10, 10), Box(0, 0, 20, 20))
    assert not result.accepted
    assert result.box == Box(5, 5, 10, 10)


def test_blank_reference_is_not_a_perfect_match():
    image = np.full((20, 20), 255, np.uint8)
    result = align_local(image, image[:5, :5], Box(2, 2, 7, 7), Box(0, 0, 20, 20))
    assert not result.accepted
    assert result.reason == "NO_REFERENCE_STRUCTURE"


def test_components_use_source_coordinates_and_filter_noise():
    image = np.full((30, 30), 255, np.uint8)
    image[12:15, 13:16] = 0
    image[18:20, 21:24] = 0
    image[11, 11] = 0
    image[0:5, 0:5] = 0
    components = connected_components(image, Box(10, 10, 26, 25), minimum_area=2)
    assert [(c.box, c.area) for c in components] == [
        (Box(13, 12, 16, 15), 9),
        (Box(21, 18, 24, 20), 6),
    ]
    envelope = text_envelope(components)
    assert envelope == Box(13, 12, 24, 20)
    assert refine_roi(envelope, Box(10, 10, 25, 22), padding=3) == Box(10, 10, 25, 22)


def test_blank_foreground_is_explicitly_empty():
    components = connected_components(np.full((5, 5), 255, np.uint8), Box(0, 0, 5, 5))
    assert components == ()
    assert text_envelope(components) is None
    assert refine_roi(None, Box(0, 0, 5, 5)) is None


@pytest.mark.parametrize(
    "image", [np.zeros((0, 5), np.uint8), np.zeros((5, 5, 3), np.uint8), np.zeros((5, 5), float)]
)
def test_invalid_image_contract(image):
    with pytest.raises(ValueError, match="grayscale"):
        connected_components(image, Box(0, 0, 5, 5))


def test_out_of_bounds_roi_and_foreign_envelope_are_rejected():
    with pytest.raises(ValueError):
        connected_components(np.zeros((5, 5), np.uint8), Box(-1, 0, 5, 5))
    with pytest.raises(ValueError):
        refine_roi(Box(0, 0, 3, 3), Box(1, 1, 5, 5))
