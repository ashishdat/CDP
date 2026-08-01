from pathlib import Path

from PIL import Image, ImageDraw

from workers.table_extraction.crop_quality import (
    CropQualityStatus,
    image_hash,
    validate_crop,
)


def test_clipped_service_units_digit_is_rejected(tmp_path: Path):
    crop = Image.new("L", (50, 30), "white")
    ImageDraw.Draw(crop).rectangle((45, 8, 49, 22), fill="black")
    path = tmp_path / "crop.png"
    crop.save(path)

    status, reasons = validate_crop(
        path,
        (10, 10, 60, 40),
        (100, 100),
        expected_hash=image_hash(path),
        registration_status="REGISTERED",
        row_status="ACTIVE",
    )

    assert status is CropQualityStatus.CLIPPED_CONTENT
    assert "RIGHT_CLIPPED" in reasons


def test_missing_image_and_unused_row_fail_closed(tmp_path: Path):
    status, _ = validate_crop(
        tmp_path / "missing.png",
        (1, 1, 10, 10),
        (20, 20),
        expected_hash="0" * 64,
        registration_status="REGISTERED",
        row_status="ACTIVE",
    )
    assert status is CropQualityStatus.MISSING_IMAGE

    path = tmp_path / "blank.png"
    Image.new("L", (20, 20), "white").save(path)
    status, _ = validate_crop(
        path,
        (0, 0, 20, 20),
        (20, 20),
        expected_hash=image_hash(path),
        registration_status="REGISTERED",
        row_status="UNUSED",
    )
    assert status is CropQualityStatus.UNUSED_ROW
