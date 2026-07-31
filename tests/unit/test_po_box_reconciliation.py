from evaluation.run_fixed_family_ocr import _reconcile_po_box_with_zip


def test_ambiguous_po_box_uses_visible_zip4_extension():
    assert _reconcile_po_box_with_zip("PO BOX 30/B/", "841300757") == "PO BOX 30757"


def test_po_box_is_not_changed_without_ambiguity_and_zip4():
    assert _reconcile_po_box_with_zip("PO BOX 123", "84130") == "PO BOX 123"
    assert _reconcile_po_box_with_zip("12 MAIN ST", "841300757") == "12 MAIN ST"
