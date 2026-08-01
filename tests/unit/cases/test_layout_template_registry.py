from packages.templates.layout_registry import LayoutTemplateRegistry


def test_all_required_layout_families_are_registered():
    templates = LayoutTemplateRegistry().load_all()
    assert set(templates) == {
        "cms1500",
        "ub_institutional",
        "psychological_receipt",
        "cms_attachment",
        "laboratory_invoice",
        "statement",
        "unknown_unstructured",
    }
    assert all(
        template.alignment_thresholds["minimum_inlier_ratio"] > 0
        for template in templates.values()
    )
