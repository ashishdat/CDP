from packages.local_text_consensus import reconcile_text


def rows(*values: str) -> list[dict]:
    return [{"raw_value": value} for value in values]


def test_selects_name_tokens_only_with_a_clear_margin() -> None:
    result = reconcile_text(
        rows("Suellen Bliss", "SUELLEN BLISS", "Swellen Bliss"),
        selector="last", minimum_support=3,
    )
    assert result.accepted and result.value == "BLISS"


def test_rejects_tied_or_weak_text() -> None:
    tied = reconcile_text(rows("Malden", "Walden"), selector="whole", minimum_support=1)
    weak = reconcile_text(rows("Nicholas"), selector="whole", minimum_support=2)
    assert not tied.accepted
    assert not weak.accepted
