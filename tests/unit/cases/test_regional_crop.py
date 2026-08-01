import numpy as np
from PIL import Image, ImageDraw

from workers.field_candidates.regional_crop import (
    CoordinateFrame,
    build_regional_crop,
)


def test_reference_box_maps_back_through_homography_and_clamps():
    image = Image.new("L", (100, 100), 255)
    ImageDraw.Draw(image).text((15, 15), "123", fill=0)
    result = build_regional_crop(
        image, (10, 10, 40, 30),
        coordinate_frame=CoordinateFrame.REFERENCE_TEMPLATE,
        reference_dimensions=(100, 100),
        candidate_to_reference_homography=np.eye(3),
        padding=(20, 20, 0, 0),
    )
    assert result.transform.final_source_box == (0, 0, 40, 30)
    assert result.transform.crop_valid


def test_blank_crop_is_explicitly_rejected():
    result = build_regional_crop(
        Image.new("L", (100, 100), 255), (10, 10, 20, 20),
        coordinate_frame=CoordinateFrame.SOURCE_PAGE,
    )
    assert not result.transform.crop_valid
    assert result.transform.failure_reason == "crop_is_mostly_blank"
