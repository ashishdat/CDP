from evaluation.derive_name_component_candidates import _plausible_complete_name
from workers.field_candidates.name_interpretations import interpret_complete_name


def test_cms_name_block_uses_last_first_convention() -> None:
    result = interpret_complete_name("LEHRMAN MATHEW", "LAST_FIRST")[0]
    assert result.first == "MATHEW"
    assert result.last == "LEHRMAN"


def test_form_labels_are_not_plausible_names() -> None:
    assert not _plausible_complete_name("PATIENT ADDRESS")
