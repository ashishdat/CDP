"""CMS-1500 charge scan must not stop after three live rows."""

from PIL import Image

from packages.templates import TemplateRegistry
from packages.templates.registry import DEFAULT_TEMPLATE_DIR


def test_fast_service_line_scan_reads_all_six_live_rows(monkeypatch):
    monkeypatch.setenv("CDP_OCR_FIELD_SCOPE", "stp_critical")
    monkeypatch.setenv("CDP_GPT4O_CROP_RESIDUAL", "0")
    monkeypatch.setenv("CDP_GPT4O_EMPTY_FINANCE", "0")

    from scripts import ocr_from_geometry as ocr

    def _recognize_one(image, field_name, bbox, router, field_type, engine_order=None):
        del image, field_name, bbox, router, field_type, engine_order
        candidates = [
            {
                "value": "200.00",
                "raw_value": "200.00",
                "engine": "paddleocr",
                "raw_confidence": 0.99,
            },
            {
                "value": "200.00",
                "raw_value": "200.00",
                "engine": "rapidocr",
                "raw_confidence": 0.99,
            },
        ]
        return candidates, [], "MOCK_DUAL_LOCAL"

    def _merge(image, bbox, **kwargs):
        del image, bbox
        return (
            kwargs["value"],
            kwargs["raw"],
            kwargs["candidates"],
            kwargs["attempts"],
            kwargs["reason"],
        )

    class _Geo:
        geometry_candidate = None
        ambiguous = True

    monkeypatch.setattr(ocr, "_recognize_one", _recognize_one)
    monkeypatch.setattr(ocr, "_merge_ruling_split_local_charge", _merge)
    monkeypatch.setattr(
        "packages.geometry_authority.monetary_geometry.read_monetary_crop",
        lambda *args, **kwargs: _Geo(),
    )

    template = TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR).get("cms1500", "02-12")
    image = Image.new(
        "L",
        (
            template.reference_dimensions.width_px,
            template.reference_dimensions.height_px,
        ),
        255,
    )
    lines = ocr.recognize_service_lines(image, router=None, template=template)
    assert len(lines) == 6
    assert [line["charges"] for line in lines] == ["200.00"] * 6
