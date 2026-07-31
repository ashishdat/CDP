from evaluation.current_comparison_report import _e


def test_report_escapes_field_values():
    assert _e("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"
