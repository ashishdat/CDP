from packages.local_numeric_consensus import reconcile_numeric


def row(value: str, model: str, variant: str) -> dict:
    return {"raw_value": value, "model_name": model, "preprocessing_variant": variant}


def test_zip_requires_cross_model_consensus_when_configured() -> None:
    result = reconcile_numeric(
        [row("02148", "v5", "a"), row("02148", "v6", "b"), row("021481", "v6", "c")],
        valid_lengths={5, 9}, minimum_support=2, minimum_model_versions=2,
    )
    assert result.accepted and result.value == "02148"


def test_tax_id_can_extract_unique_nine_digit_run_but_still_requires_support() -> None:
    result = reconcile_numeric(
        [row("942880847", "v6", "a"), row("十942880847", "v6", "b")],
        valid_lengths={9}, minimum_support=2,
    )
    assert result.accepted and result.value == "942880847"
    blocked = reconcile_numeric(
        [row("942880847", "v6", "a")], valid_lengths={9}, minimum_support=2,
    )
    assert not blocked.accepted
