import json

from app import STAGES, process_one


def test_load_failure_preserves_execution_state(tmp_path):
    path, state = process_one(tmp_path / "missing.yaml", output_root=tmp_path / "runs")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == state
    assert saved["status"] == "FAILED"
    assert saved["stages"]["load"] == "UNAVAILABLE"
    assert all(saved["stages"][name] == "SKIPPED" for name in STAGES if name != "load")
    assert saved["latency_ms"]["total"] >= saved["latency_ms"]["load"]
    assert saved["errors"][0]["type"] == "FileNotFoundError"
    assert saved["page_count"] == 0


def test_registration_rejects_unresolved_classification():
    from types import SimpleNamespace

    from app import register_classified_document
    from packages.templates.registry import TemplateRegistry

    route = SimpleNamespace(needs_review=True, template=None, selected_page_number=None)
    result = register_classified_document([], route, TemplateRegistry())
    assert result["status"] == "UNAVAILABLE"
    assert result["transform_matrix"] is None
    assert not result["accepted"]


def test_registration_missing_reference_preserves_failure():
    from types import SimpleNamespace

    from PIL import Image

    from app import register_classified_document
    from packages.domain.enums import ClaimFormType
    from packages.templates.registry import TemplateRegistry

    registry = TemplateRegistry.load_from_directory(canonical_dir=None)
    template = registry.latest_for_form_type(ClaimFormType.CMS1500)
    template = template.model_copy(update={"reference_image_path": None})
    route = SimpleNamespace(needs_review=False, template=template, selected_page_number=1)
    with Image.new("L", (30, 30)) as image:
        result = register_classified_document([image], route, registry)
    assert result["reason"] == "REFERENCE_TEMPLATE_IMAGE_UNAVAILABLE"
    assert result["status"] == "UNAVAILABLE"
    assert not result["accepted"]


def test_registration_rejects_invalid_selected_page():
    from types import SimpleNamespace

    from app import register_classified_document
    from packages.templates.registry import TemplateRegistry

    route = SimpleNamespace(needs_review=False, template=object(), selected_page_number=0)
    result = register_classified_document([], route, TemplateRegistry())
    assert result["status"] == "FAILED"
    assert result["reason"] == "SELECTED_PAGE_OUT_OF_RANGE"


def test_real_registration_rejection_is_serializable(tmp_path):
    from types import SimpleNamespace

    from PIL import Image

    from app import register_classified_document
    from packages.domain.enums import ClaimFormType
    from packages.templates.registry import TemplateRegistry

    registry = TemplateRegistry.load_from_directory(canonical_dir=None)
    template = registry.latest_for_form_type(ClaimFormType.CMS1500)
    template = template.model_copy(update={"reference_image_path": "blank.png"})
    registry.register(template, source_dir=tmp_path)
    dimensions = template.reference_dimensions
    with Image.new("L", (dimensions.width_px, dimensions.height_px), 255) as image:
        image.save(tmp_path / "blank.png")
        route = SimpleNamespace(needs_review=False, template=template, selected_page_number=1)
        result = register_classified_document([image], route, registry)
    assert result["status"] == "FAILED"
    assert result["evidence"]["accepted"] is False
    assert result["transform_matrix"] is None
    json.dumps(result, allow_nan=False)
