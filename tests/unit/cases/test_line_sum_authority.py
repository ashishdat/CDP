from decimal import Decimal

from packages.claim_evidence.line_sum_authority import (
    amounts_corroborate,
    candidate_independence_key,
    candidates_are_independent,
    is_decimal_place_shift,
    is_embedded_charge_digit_fragment,
    is_implausible_charge_total,
    is_implausible_corroborator,
    is_suspicious_tiny_total,
    line_has_dual_engine_agreement,
    line_has_gpt4o_local_consensus,
    line_sum_auto_eligible,
    line_sum_total,
    should_defer_box28_to_line_sum,
)
from packages.extraction_recovery.field_cascade import semantic_accept


def test_suspicious_tiny_matches_cascade_rule():
    assert is_suspicious_tiny_total(Decimal("2.22"))
    assert not is_suspicious_tiny_total(Decimal("22.00"))
    assert not is_suspicious_tiny_total(Decimal("1600.00"))


def test_embedded_charge_digit_fragment():
    assert is_embedded_charge_digit_fragment("3", "105.00")
    assert is_embedded_charge_digit_fragment("03.00", "105.00")
    assert not is_embedded_charge_digit_fragment("105.00", "105.00")
    assert not is_embedded_charge_digit_fragment("2001.00", "200.00")
    assert not is_embedded_charge_digit_fragment("200.00", "2001.00")
    assert not is_embedded_charge_digit_fragment("15.00", "105.00")
    assert not is_embedded_charge_digit_fragment("10", "105.00")


def test_implausible_box28_digit_soup():
    assert is_implausible_charge_total("208408.00")
    assert is_implausible_charge_total("420840.00")
    assert not is_implausible_charge_total("2084.00")
    assert is_implausible_corroborator("208408.00", "200.00")
    assert is_implausible_corroborator("2084.00", "200.00")  # >3× line-sum
    assert is_implausible_corroborator("22.00", "400.00")  # <1/3 line-sum
    assert is_implausible_corroborator("900.00", "200.00")  # 4.5× noise
    assert not is_implausible_corroborator("210.00", "200.00")
    assert not is_implausible_corroborator("222.00", "200.00")  # near-miss stays
    # Place-adjacent rivals must not be ignored (would unlock false STP).
    assert not is_implausible_corroborator("1571.07", "157.00")
    assert not is_implausible_corroborator("2281.32", "228.00")
    # DI cents-column split of the line total is corroborator junk.
    assert is_implausible_corroborator("39.00", "97.39")
    assert not is_implausible_corroborator("40.00", "97.39")
    ok, reason = semantic_accept("total_charge", "208408.00")
    assert not ok and reason == "CURRENCY_IMPLAUSIBLE_TOTAL"


def test_inflated_conflict_agent_amount_is_not_open_source_authority():
    """Paddle ``200400`` must not let a conflict agent override ``200.00``."""
    from packages.claim_evidence.line_sum_authority import (
        llm_charge_pick_has_open_source_authority,
    )

    candidates = [
        {"engine": "anthropic_claude_crop", "value": "200.00", "raw_value": "200.00"},
        {"engine": "anthropic_claude_crop", "value": "2004.00", "raw_value": "2004.00"},
        {"engine": "paddleocr", "value": "2004.00", "raw_value": "200400"},
    ]
    assert not llm_charge_pick_has_open_source_authority("2004.00", candidates)
    assert not llm_charge_pick_has_open_source_authority("200.00", candidates)


def test_di_confirmed_inflated_local_stem_is_open_source_authority():
    """EJGE.009: Rapid ``12000`` + DI ``1200`` needs incomplete 3×$200 grid."""
    from packages.claim_evidence.line_sum_authority import (
        llm_charge_pick_has_open_source_authority,
    )

    candidates = [
        {"engine": "anthropic_claude_crop", "value": "1200.00"},
        {"engine": "azure_document_intelligence_read", "value": "1200.00"},
        {"engine": "rapidocr", "value": "12000.00"},
    ]
    lines = [
        {"charges": "200.00", "line_charge_selection": {"disposition": "SELECTED_LOCAL_CHARGE", "amount": "200.00"}},
        {"charges": "200.00", "line_charge_selection": {"disposition": "SELECTED_LOCAL_CHARGE", "amount": "200.00"}},
        {"charges": "200.00", "line_charge_selection": {"disposition": "SELECTED_LOCAL_CHARGE", "amount": "200.00"}},
    ]
    assert llm_charge_pick_has_open_source_authority("1200.00", candidates, lines)
    # Without the truncated grid, DI+inflated rapid alone is not enough (DJKN.005).
    assert not llm_charge_pick_has_open_source_authority("1200.00", candidates, None)
    assert not llm_charge_pick_has_open_source_authority(
        "200.00",
        [
            {"engine": "anthropic_claude_crop", "value": "200.00"},
            {"engine": "azure_document_intelligence_read", "value": "200.00"},
            {"engine": "paddleocr", "value": "2001.00"},
        ],
        None,
    )
    # Without DI, an inflated local alone is not enough.
    assert not llm_charge_pick_has_open_source_authority(
        "1200.00",
        [
            {"engine": "anthropic_claude_crop", "value": "1200.00"},
            {"engine": "rapidocr", "value": "12000.00"},
        ],
        lines,
    )
    # A non-scale local rival still blocks.
    assert not llm_charge_pick_has_open_source_authority(
        "175.00",
        [
            {"engine": "azure_document_intelligence_read", "value": "175.00"},
            {"engine": "rapidocr", "value": "1751.00"},
            {"engine": "paddleocr", "value": "5175.00"},
        ],
        lines,
    )


def test_di_vs_non_twin_digit_whitelist_soup_is_open_source_authority():
    """EJG7.003: DI ``1825`` vs paddle whitelist ``4825``; twins stay HITL."""
    from packages.claim_evidence.line_sum_authority import (
        llm_charge_pick_has_open_source_authority,
    )

    ejg7_003 = [
        {
            "engine": "azure_document_intelligence_read",
            "value": "1825.00",
            "raw_value": ".TOTAL CHANGE 1825 00 2 :",
            "preprocessing_variant": "charge_azure_di_crop_residual",
        },
        {
            "engine": "anthropic_claude_crop",
            "value": "1825.00",
            "preprocessing_variant": "conflict_agent_financial",
        },
        {
            "engine": "paddleocr",
            "value": "4825.00",
            "raw_value": "482500",
            "preprocessing_variant": "charge_digit_whitelist_fast:full",
        },
    ]
    assert llm_charge_pick_has_open_source_authority("1825.00", ejg7_003, None)
    # Same digits without whitelist prep remain a real local rival.
    assert not llm_charge_pick_has_open_source_authority(
        "1825.00",
        [
            {"engine": "azure_document_intelligence_read", "value": "1825.00"},
            {"engine": "paddleocr", "value": "4825.00", "preprocessing_variant": "full"},
        ],
        None,
    )
    # DJKN.005 / DJKN.007: digit-drop twin whitelist soup must not unlock DI.
    assert not llm_charge_pick_has_open_source_authority(
        "200.00",
        [
            {"engine": "azure_document_intelligence_read", "value": "200.00"},
            {
                "engine": "paddleocr",
                "value": "2001.00",
                "raw_value": "200100",
                "preprocessing_variant": "charge_digit_whitelist_fast:full",
            },
        ],
        None,
    )
    assert not llm_charge_pick_has_open_source_authority(
        "200.00",
        [
            {"engine": "azure_document_intelligence_read", "value": "200.00"},
            {
                "engine": "paddleocr",
                "value": "2004.00",
                "raw_value": "200400",
                "preprocessing_variant": "charge_digit_whitelist_fast:full",
            },
        ],
        None,
    )


def test_incomplete_uniform_line_grid_does_not_block_box28():
    """EJGE.007: 3×$200 OCR vs printed Box 28 $1200 is not a rival total."""
    from packages.claim_evidence.line_sum_authority import (
        charge_conflicts_with_plausible_line_sum,
        incomplete_uniform_line_grid_explains_box28,
    )

    lines = [
        {
            "charges": "200.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "200.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
            },
        },
        {
            "charges": "200.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "200.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
            },
        },
        {
            "charges": "200.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "200.00",
                "reason": "DUAL_LOCAL_CHARGE_COLUMN",
            },
        },
    ]
    assert incomplete_uniform_line_grid_explains_box28("1200.00", lines)
    assert not charge_conflicts_with_plausible_line_sum("1200.00", lines)
    # Incomplete-grid Box 28 must not be deferred away for line-sum ownership.
    assert not should_defer_box28_to_line_sum("1200.00", lines)
    # Inflated Claude/paddle 4200 implies 21 rows — beyond CMS-1500 grid.
    assert not incomplete_uniform_line_grid_explains_box28("4200.00", lines)
    assert charge_conflicts_with_plausible_line_sum("4200.00", lines)
    from packages.claim_evidence.line_sum_authority import (
        chosen_exceeds_cms_uniform_line_grid,
    )

    assert chosen_exceeds_cms_uniform_line_grid("4200.00", lines)
    assert not chosen_exceeds_cms_uniform_line_grid("1200.00", lines)
    from packages.claim_evidence.line_sum_authority import (
        llm_charge_pick_has_open_source_authority,
        prefer_incomplete_grid_box28,
        _di_agrees_on_charge_amount,
    )

    cands = [
        {"engine": "paddleocr", "value": "4200.00"},
        {"engine": "anthropic_claude_crop", "value": "1200.00"},
        {
            "engine": "azure_document_intelligence_read",
            "value": "23.00",
            "raw_value": ".TOTAL CHARGE 1200; 00 23 $",
        },
    ]
    assert _di_agrees_on_charge_amount("1200.00", cands)
    assert prefer_incomplete_grid_box28("4200.00", cands, lines) == "1200.00"
    assert llm_charge_pick_has_open_source_authority("1200.00", cands, lines)
    assert not llm_charge_pick_has_open_source_authority("4200.00", cands, lines)

    # EJG7.016: DI+paddle 600 with only 2 equal $150 lines.
    from packages.claim_evidence.line_sum_authority import (
        di_backed_incomplete_grid_explains_box28,
    )

    two = [
        {
            "charges": "150.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "150.00",
            },
        },
        {
            "charges": "150.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "150.00",
            },
        },
    ]
    di_local = [
        {"engine": "paddleocr", "value": "600.00"},
        {
            "engine": "azure_document_intelligence_read",
            "value": "600.00",
            "raw_value": "$600 :00",
        },
    ]
    assert not incomplete_uniform_line_grid_explains_box28("600.00", two)
    assert di_backed_incomplete_grid_explains_box28("600.00", two, di_local)
    assert not charge_conflicts_with_plausible_line_sum("600.00", two, di_local)
    assert not should_defer_box28_to_line_sum("600.00", two, candidates=di_local)
    # Two equal lines alone are too weak (EJG7.016 2×150 vs Box 600).
    two_lines = lines[:2]
    assert not incomplete_uniform_line_grid_explains_box28("600.00", two_lines)
    assert charge_conflicts_with_plausible_line_sum("600.00", two_lines)
    # Mixed line amounts are a real rival.
    mixed = [
        {"charges": "150.00", "line_charge_selection": {"disposition": "SELECTED_LOCAL_CHARGE", "amount": "150.00"}},
        {"charges": "1.50", "line_charge_selection": {"disposition": "SELECTED_LOCAL_CHARGE", "amount": "1.50"}},
    ]
    assert not incomplete_uniform_line_grid_explains_box28("300.00", mixed)
    assert charge_conflicts_with_plausible_line_sum("300.00", mixed)


def test_form_ruling_noise_charge_ignored_not_auto():
    """Form-ruling digit soup (208408) must not AUTO via junk corroboration."""
    lines = [
        {
            "charges": "200.00",
            "producing_engine": "paddleocr",
            "candidates": [{"value": "200.00", "engine": "paddleocr"}],
        }
    ]
    ok, reason = line_sum_auto_eligible(lines, corroborating_values=["208408.00"])
    assert not ok
    assert reason == "SINGLE_LINE_REQUIRES_DI"
    assert is_implausible_charge_total("208408")


def test_defer_when_box28_empty_or_tiny():
    lines = [{"charges": "498.00"}, {"charges": "66.00"}]
    assert should_defer_box28_to_line_sum(None, lines)
    assert should_defer_box28_to_line_sum("2.22", lines)
    assert should_defer_box28_to_line_sum("208408.00", lines)
    assert line_sum_total(lines) == "564.00"


def test_defer_when_uncalibrated_ocr_contradicts_multi_line_sum():
    lines = [{"charges": "200.00"}, {"charges": "200.00"}, {"charges": "1200.00"}]
    assert should_defer_box28_to_line_sum("198240.00", lines)
    assert not should_defer_box28_to_line_sum("1600.00", lines)


def test_single_line_does_not_override_plausible_box28():
    lines = [{"charges": "305.00"}]
    assert not should_defer_box28_to_line_sum("305.00", lines)
    # Near-miss box-28 stays with OCR (diff 95 < 50% of 305).
    assert not should_defer_box28_to_line_sum("400.00", lines)
    assert should_defer_box28_to_line_sum("2.22", lines)


def test_single_line_defers_wild_box28_contradiction():
    """v11.5: box-28 22.00 vs single line 305.00 is not a plausible total."""
    lines = [{"charges": "305.00"}]
    assert should_defer_box28_to_line_sum("22.00", lines)
    assert line_sum_total(lines) == "305.00"


def test_amounts_corroborate_requires_exact_monetary_equality():
    assert amounts_corroborate("400.00", "400.00")
    assert not amounts_corroborate("157.00", "1571.00")
    assert not amounts_corroborate("270.00", "424.00")
    assert not amounts_corroborate("600.00", "1600.00")
    # Same four digits, cents column moved. Not a dropped leading digit.
    assert not amounts_corroborate("49.72", "4972.00")
    assert not amounts_corroborate("4972.00", "49.72")


def test_candidate_independence_helpers():
    key = candidate_independence_key(
        {
            "producing_engine": "paddleocr",
            "source_crop_id": "crop-a",
            "preprocessing_path": "deskew",
            "value": "200.00",
            "confidence": 0.9,
            "parent_evidence_id": "ev-1",
            "independence_group": "PADDLE_FAMILY",
        }
    )
    assert key[0] == "paddleocr"
    assert key[1] == "crop-a"
    assert key[5] == "ev-1"
    assert key[6] == "PADDLE_FAMILY"

    a = {"engine": "paddleocr", "parent_evidence_id": "shared", "value": "200.00"}
    b = {"engine": "azure_gpt4o_crop", "parent_evidence_id": "shared", "value": "200.00"}
    assert not candidates_are_independent(a, b)

    c = {"engine": "paddleocr", "source_crop_id": "same-crop", "value": "200.00"}
    d = {"engine": "azure_gpt4o_crop", "source_crop_id": "same-crop", "value": "200.00"}
    assert not candidates_are_independent(c, d)

    e = {"engine": "paddleocr", "independence_group": "CLOUD_AI_FAMILY", "value": "200.00"}
    f = {"engine": "azure_gpt4o_crop", "independence_group": "CLOUD_AI_FAMILY", "value": "200.00"}
    assert not candidates_are_independent(e, f)

    g = {
        "engine": "paddleocr",
        "source_crop_id": "crop-1",
        "independence_group": "PADDLE_FAMILY",
        "value": "200.00",
    }
    h = {
        "engine": "azure_gpt4o_crop",
        "source_crop_id": "crop-2",
        "independence_group": "CLOUD_AI_FAMILY",
        "value": "200.00",
    }
    assert candidates_are_independent(g, h)


def test_gpt4o_only_with_unusable_local_not_eligible():
    """GPT-4o agrees with its own selected value but local OCR unusable → HITL."""
    line = {
        "charges": "200.00",
        "producing_engine": "azure_gpt4o_crop",
        "candidates": [
            {"value": "2.00", "engine": "paddleocr"},  # form-noise shell
            {"value": "200.00", "engine": "azure_gpt4o_crop"},
        ],
    }
    assert not line_has_gpt4o_local_consensus(line)
    ok, reason = line_sum_auto_eligible([line])
    assert not ok and reason == "SINGLE_LINE_REQUIRES_DI"


def test_gpt4o_plus_blank_local_shell_not_eligible():
    line = {
        "charges": "200.00",
        "producing_engine": "azure_gpt4o_crop",
        "candidates": [
            {"value": "", "engine": "paddleocr"},
            {"value": "200.00", "engine": "azure_gpt4o_crop"},
        ],
    }
    assert not line_has_gpt4o_local_consensus(line)
    ok, reason = line_sum_auto_eligible([line])
    assert not ok and reason == "SINGLE_LINE_REQUIRES_DI"


def test_gpt4o_and_local_same_parent_evidence_not_eligible():
    line = {
        "charges": "200.00",
        "producing_engine": "paddleocr",
        "candidates": [
            {
                "value": "200.00",
                "engine": "paddleocr",
                "parent_evidence_id": "upstream-1",
                "source_crop_id": "crop-a",
            },
            {
                "value": "200.00",
                "engine": "azure_gpt4o_crop",
                "parent_evidence_id": "upstream-1",
                "source_crop_id": "crop-b",
            },
        ],
    }
    assert not candidates_are_independent(
        line["candidates"][0], line["candidates"][1]
    )
    assert not line_has_gpt4o_local_consensus(line)
    ok, reason = line_sum_auto_eligible([line])
    assert not ok and reason == "SINGLE_LINE_REQUIRES_DI"


def test_local_and_gpt4o_disagree_not_eligible():
    line = {
        "charges": "200.00",
        "producing_engine": "paddleocr",
        "candidates": [
            {"value": "350.00", "engine": "paddleocr"},
            {"value": "200.00", "engine": "azure_gpt4o_crop"},
        ],
    }
    assert not line_has_gpt4o_local_consensus(line)
    ok, reason = line_sum_auto_eligible([line])
    assert not ok and reason == "SINGLE_LINE_REQUIRES_DI"


def test_pos_like_local_does_not_veto_gpt_consensus():
    """Rapid POS 11 is not a vote; a later paddle 270 confirms the vision read."""
    line = {
        "charges": "270.00",
        "candidates": [
            {"value": "", "engine": "paddleocr", "raw_value": "1\n4\n1"},
            {"value": "11.00", "engine": "rapidocr"},
            {"value": "270.00", "engine": "paddleocr", "producing_engine": "tesseract_digits"},
            {"value": "270.00", "engine": "azure_gpt4o_crop"},
        ],
    }
    assert line_has_gpt4o_local_consensus(line)


def test_digit_drop_twins_not_dual_engine_or_gpt4o_consensus():
    """13 vs 131 must not AUTO without authoritative box-28 / DI signal."""
    twin_dual = {
        "charges": "131.00",
        "candidates": [
            {"value": "13.00", "engine": "paddleocr"},
            {"value": "131.00", "engine": "rapidocr"},
        ],
    }
    assert not line_has_dual_engine_agreement(twin_dual)

    twin_gpt = {
        "charges": "131.00",
        "producing_engine": "paddleocr",
        "candidates": [
            {"value": "13.00", "engine": "paddleocr"},
            {"value": "131.00", "engine": "azure_gpt4o_crop"},
        ],
    }
    assert not line_has_gpt4o_local_consensus(twin_gpt)

    twin_gpt_selected_long = {
        "charges": "6430.00",
        "producing_engine": "azure_gpt4o_crop",
        "candidates": [
            {"value": "643.00", "engine": "paddleocr"},
            {"value": "6430.00", "engine": "azure_gpt4o_crop"},
        ],
    }
    assert not line_has_gpt4o_local_consensus(twin_gpt_selected_long)

    multi = [
        twin_dual,
        {
            "charges": "4.00",
            "candidates": [
                {"value": "4.00", "engine": "paddleocr"},
                {"value": "4.00", "engine": "rapidocr"},
            ],
        },
    ]
    ok, reason = line_sum_auto_eligible(multi)
    assert not ok and reason == "MULTI_LINE_UNCORROBORATED"


def test_multi_line_one_uncorroborated():
    lines = [
        {
            "charges": "200.00",
            "candidates": [
                {"value": "200.00", "engine": "paddleocr"},
                {"value": "200.00", "engine": "rapidocr"},
            ],
        },
        {
            "charges": "150.00",
            "candidates": [{"value": "150.00", "engine": "paddleocr"}],
        },
    ]
    ok, reason = line_sum_auto_eligible(lines)
    assert not ok and reason == "MULTI_LINE_UNCORROBORATED"


def test_plausible_incorrect_box28_vs_line_sum_conflict():
    bare = [{"charges": "424.00", "candidates": [{"value": "424.00", "engine": "paddleocr"}]}]
    ok, reason = line_sum_auto_eligible(bare, corroborating_values=["270.00"])
    assert not ok and reason == "BOX28_OR_DI_CONFLICT"


def test_dual_engine_paddle_rapid_exact_agree():
    dual = [
        {
            "charges": "200.00",
            "candidates": [
                {"value": "200.00", "engine": "paddleocr"},
                {"value": "200.00", "engine": "rapidocr"},
            ],
        },
        {
            "charges": "200.00",
            "candidates": [
                {"value": "200.00", "engine": "paddleocr"},
                {"value": "200.00", "engine": "rapidocr"},
            ],
        },
    ]
    assert line_has_dual_engine_agreement(dual[0])
    ok, reason = line_sum_auto_eligible(dual)
    assert ok and reason == "DUAL_ENGINE_LINE_AGREEMENT"
    ok, reason = line_sum_auto_eligible(dual, corroborating_values=["400.00"])
    assert ok and reason == "BOX28_OR_DI_CORROBORATED"


def test_usable_local_plus_independent_gpt4o_exact_agree():
    """Usable paddle + independent gpt4o on independently selected local value."""
    line = {
        "charges": "200.00",
        "producing_engine": "paddleocr",
        "candidates": [
            {
                "value": "200.00",
                "engine": "paddleocr",
                "source_crop_id": "local-crop",
                "independence_group": "PADDLE_FAMILY",
            },
            {
                "value": "200.00",
                "engine": "azure_gpt4o_crop",
                "source_crop_id": "gpt-crop",
                "independence_group": "CLOUD_AI_FAMILY",
            },
        ],
    }
    assert line_has_gpt4o_local_consensus(line)
    ok, reason = line_sum_auto_eligible([line])
    assert ok and reason == "SINGLE_LINE_GPT4O_LOCAL"
    ok, reason = line_sum_auto_eligible([line], corroborating_values=["200.00"])
    assert ok and reason == "SINGLE_LINE_GPT4O_LOCAL"


def test_gpt4o_selected_with_agreeing_local_counts_as_confirm():
    """Local independent confirmation still counts when selection is gpt-4o-attributed."""
    line = {
        "charges": "200.00",
        "producing_engine": "azure_gpt4o_crop",
        "candidates": [
            {
                "value": "200.00",
                "engine": "paddleocr",
                "source_crop_id": "local-crop",
            },
            {
                "value": "200.00",
                "engine": "azure_gpt4o_crop",
                "source_crop_id": "gpt-crop",
            },
        ],
    }
    assert line_has_gpt4o_local_consensus(line)
    ok, reason = line_sum_auto_eligible([line])
    assert ok and reason == "SINGLE_LINE_GPT4O_LOCAL"
    ok, reason = line_sum_auto_eligible([line], corroborating_values=["200.00"])
    assert ok and reason == "SINGLE_LINE_GPT4O_LOCAL"


def test_box28_exact_corroborates_line_sum():
    bare = [{"charges": "424.00", "candidates": [{"value": "424.00", "engine": "paddleocr"}]}]
    ok, reason = line_sum_auto_eligible(bare, corroborating_values=["424.00"])
    assert ok and reason == "BOX28_OR_DI_CORROBORATED"


def test_line_sum_auto_requires_dual_engine_or_di():
    bare = [{"charges": "424.00", "candidates": [{"value": "424.00", "engine": "paddleocr"}]}]
    ok, reason = line_sum_auto_eligible(bare)
    assert not ok
    assert reason == "SINGLE_LINE_REQUIRES_DI"

    # Single-line paddle+rapid without Box 28 stays HITL (need independent total).
    single_dual = [
        {
            "charges": "222.00",
            "candidates": [
                {"value": "222.00", "engine": "paddleocr"},
                {"value": "222.00", "engine": "rapidocr"},
            ],
        }
    ]
    ok, reason = line_sum_auto_eligible(single_dual)
    assert not ok and reason == "SINGLE_LINE_DUAL_ENGINE_NEEDS_BOX28"
    ok, reason = line_sum_auto_eligible(single_dual, corroborating_values=["222.00"])
    assert ok and reason == "BOX28_OR_DI_CORROBORATED"

    # paddle+rapid+gpt-4o consensus AUTOs via gpt-4o+local (empty Box 28 OK).
    single_triple = [
        {
            "charges": "200.00",
            "producing_engine": "paddleocr",
            "candidates": [
                {"value": "200.00", "engine": "paddleocr", "source_crop_id": "c1"},
                {"value": "200.00", "engine": "rapidocr", "source_crop_id": "c2"},
                {"value": "200.00", "engine": "azure_gpt4o_crop", "source_crop_id": "c3"},
            ],
        }
    ]
    ok, reason = line_sum_auto_eligible(single_triple)
    assert ok and reason == "SINGLE_LINE_GPT4O_LOCAL"

    single_gpt_paddle = [
        {
            "charges": "200.00",
            "producing_engine": "paddleocr",
            "candidates": [
                {"value": "200.00", "engine": "paddleocr", "source_crop_id": "c1"},
                {"value": "200.00", "engine": "azure_gpt4o_crop", "source_crop_id": "c2"},
            ],
        }
    ]
    ok, reason = line_sum_auto_eligible(single_gpt_paddle)
    assert ok and reason == "SINGLE_LINE_GPT4O_LOCAL"

    conflict_local = [
        {
            "charges": "200.00",
            "producing_engine": "paddleocr",
            "candidates": [
                {"value": "350.00", "engine": "paddleocr"},
                {"value": "200.00", "engine": "azure_gpt4o_crop"},
            ],
        }
    ]
    ok, reason = line_sum_auto_eligible(conflict_local)
    assert not ok and reason == "SINGLE_LINE_REQUIRES_DI"

    # Junk box-28 is ignored; gpt-4o+local still AUTOs.
    ok, reason = line_sum_auto_eligible(
        single_triple, corroborating_values=["208408.00"]
    )
    assert ok and reason == "SINGLE_LINE_GPT4O_LOCAL"

    # Near-miss box-28 conflicts with the line sum → HITL.
    ok, reason = line_sum_auto_eligible(
        single_triple, corroborating_values=["222.00"]
    )
    assert not ok and reason == "BOX28_OR_DI_CONFLICT"

    # Matching Box 28 with gpt-4o+local still AUTOs (line consensus path).
    ok, reason = line_sum_auto_eligible(
        single_triple, corroborating_values=["200.00"]
    )
    assert ok and reason == "SINGLE_LINE_GPT4O_LOCAL"

    # Cents column: vision+local 49.72, DI digits 4972, truncations are not rivals.
    placed = [
        {
            "charges": "49.72",
            "producing_engine": "rapidocr",
            "candidates": [
                {"value": "49.72", "engine": "rapidocr", "source_crop_id": "c1"},
                {"value": "49.72", "engine": "anthropic_claude_crop", "source_crop_id": "c2"},
            ],
        }
    ]
    ok, reason = line_sum_auto_eligible(
        placed, corroborating_values=["4972.00", "972.00", "72.00"]
    )
    assert ok and reason == "DECIMAL_COLUMN_VISION_LOCAL"
    # Digit-drop is not a cents column. 13 vs 131 stays closed.
    short = [
        {
            "charges": "13.00",
            "producing_engine": "paddleocr",
            "candidates": [
                {"value": "13.00", "engine": "paddleocr", "source_crop_id": "c1"},
                {"value": "13.00", "engine": "anthropic_claude_crop", "source_crop_id": "c2"},
            ],
        }
    ]
    ok, reason = line_sum_auto_eligible(short, corroborating_values=["131.00"])
    assert not ok and reason == "BOX28_OR_DI_CONFLICT"
    # Paddle's unplaced 4972 must not cancel rapid+Claude on the placed amount.
    mixed = [
        {
            "charges": "49.72",
            "producing_engine": "rapidocr",
            "candidates": [
                {"value": "4972.00", "engine": "paddleocr", "source_crop_id": "c1"},
                {"value": "49.72", "engine": "rapidocr", "source_crop_id": "c2"},
                {"value": "49.72", "engine": "anthropic_claude_crop", "source_crop_id": "c3"},
            ],
        }
    ]
    ok, reason = line_sum_auto_eligible(
        mixed, corroborating_values=["4972.00", "972.00", "72.00"]
    )
    assert ok and reason == "DECIMAL_COLUMN_VISION_LOCAL"

    # Multi-line gpt-4o+local without Box 28 AUTOs.
    multi_gpt = [
        {
            "charges": "200.00",
            "producing_engine": "paddleocr",
            "candidates": [
                {"value": "200.00", "engine": "paddleocr", "source_crop_id": "a1"},
                {"value": "200.00", "engine": "azure_gpt4o_crop", "source_crop_id": "a2"},
            ],
        },
        {
            "charges": "200.00",
            "producing_engine": "rapidocr",
            "candidates": [
                {"value": "200.00", "engine": "rapidocr", "source_crop_id": "b1"},
                {"value": "200.00", "engine": "azure_gpt4o_crop", "source_crop_id": "b2"},
            ],
        },
    ]
    ok, reason = line_sum_auto_eligible(multi_gpt)
    assert ok and reason == "MULTI_LINE_GPT4O_LOCAL"
    ok, reason = line_sum_auto_eligible(multi_gpt, corroborating_values=["400.00"])
    assert ok and reason == "MULTI_LINE_GPT4O_LOCAL"

    # Digit-drop twin gpt-4o↔local is NOT consensus (exact/$1 only on this path).
    twin_gpt = [
        {
            "charges": "6430.00",
            "producing_engine": "azure_gpt4o_crop",
            "candidates": [
                {"value": "643.00", "engine": "paddleocr"},
                {"value": "6430.00", "engine": "azure_gpt4o_crop"},
            ],
        }
    ]
    ok, reason = line_sum_auto_eligible(twin_gpt)
    assert not ok and reason == "SINGLE_LINE_REQUIRES_DI"

    dual = [
        {
            "charges": "200.00",
            "candidates": [
                {"value": "200.00", "engine": "paddleocr"},
                {"value": "200.00", "engine": "rapidocr"},
            ],
        },
        {
            "charges": "200.00",
            "candidates": [
                {"value": "200.00", "engine": "paddleocr"},
                {"value": "200.00", "engine": "rapidocr"},
            ],
        },
    ]
    ok, reason = line_sum_auto_eligible(dual)
    assert ok and reason == "DUAL_ENGINE_LINE_AGREEMENT"

    # paddle + gpt-4o on every line AUTOs without Box 28.
    paddle_gpt4o = [
        {
            "charges": "485.00",
            "producing_engine": "paddleocr",
            "candidates": [
                {"value": "485.00", "engine": "paddleocr", "source_crop_id": "p1"},
                {"value": "485.00", "engine": "azure_gpt4o_crop", "source_crop_id": "g1"},
            ],
        },
        {
            "charges": "485.00",
            "producing_engine": "paddleocr",
            "candidates": [
                {"value": "485.00", "engine": "paddleocr", "source_crop_id": "p2"},
                {"value": "485.00", "engine": "azure_gpt4o_crop", "source_crop_id": "g2"},
            ],
        },
    ]
    ok, reason = line_sum_auto_eligible(paddle_gpt4o)
    assert ok and reason == "MULTI_LINE_GPT4O_LOCAL"
    ok, reason = line_sum_auto_eligible(paddle_gpt4o, corroborating_values=["970.00"])
    assert ok and reason == "MULTI_LINE_GPT4O_LOCAL"

    # paddle-only multi-line (no gpt-4o) still needs dual-engine on each line.
    paddle_only_multi = [
        {
            "charges": "485.00",
            "candidates": [{"value": "485.00", "engine": "paddleocr"}],
        },
        {
            "charges": "485.00",
            "candidates": [{"value": "485.00", "engine": "paddleocr"}],
        },
    ]
    ok, reason = line_sum_auto_eligible(paddle_only_multi)
    assert not ok and reason == "MULTI_LINE_UNCORROBORATED"

    ok, reason = line_sum_auto_eligible(bare, corroborating_values=["424.00"])
    assert ok and reason == "BOX28_OR_DI_CORROBORATED"

    ok, reason = line_sum_auto_eligible(bare, corroborating_values=["270.00"])
    assert not ok and reason == "BOX28_OR_DI_CONFLICT"

    # Digit-drop twin across engines is not dual-engine agreement for AUTO.
    twin_line = [
        {
            "charges": "131.00",
            "candidates": [
                {"value": "13.00", "engine": "paddleocr"},
                {"value": "131.00", "engine": "rapidocr"},
            ],
        },
        {
            "charges": "4.00",
            "candidates": [
                {"value": "4.00", "engine": "paddleocr"},
                {"value": "4.00", "engine": "rapidocr"},
            ],
        },
    ]
    ok, reason = line_sum_auto_eligible(twin_line)
    assert not ok and reason == "MULTI_LINE_UNCORROBORATED"


def test_pos_like_line_sum_rejected_without_box28():
    """M048DJJF.013 guard: POS 11.00 must not AUTO via line-sum."""
    lines = [
        {
            "charges": "11.00",
            "producing_engine": "rapidocr",
            "candidates": [
                {"value": "11.00", "engine": "rapidocr"},
                {"value": "11.00", "engine": "paddleocr"},
            ],
        }
    ]
    ok, reason = line_sum_auto_eligible(lines)
    assert not ok
    assert reason == "POS_LIKE_LINE_SUM_REJECTED"


def test_deferred_box28_shell_filtered_unlocks_gpt4o_local_line_sum():
    """M.001: deferred OCR 825 must not veto gpt-4o+local line Σ 450."""
    lines = [
        {
            "charges": "450.00",
            "candidates": [
                {"value": "450.00", "engine": "paddleocr"},
                {"value": "450.00", "engine": "rapidocr"},
                {"value": "450.00", "engine": "azure_gpt4o_crop"},
            ],
        }
    ]
    assert should_defer_box28_to_line_sum("825.00", lines)
    raw_corr = ["825.00"]
    filtered = [
        v for v in raw_corr if not should_defer_box28_to_line_sum(v, lines)
    ]
    ok_old, reason_old = line_sum_auto_eligible(
        lines, box28_value=None, corroborating_values=raw_corr
    )
    assert not ok_old and reason_old == "BOX28_OR_DI_CONFLICT"
    ok_new, reason_new = line_sum_auto_eligible(
        lines, box28_value=None, corroborating_values=filtered
    )
    assert ok_new and reason_new == "SINGLE_LINE_GPT4O_LOCAL"


def test_decimal_place_shift_box28_is_deferrable_against_line_sum():
    """DJKN.024: gpt-4o Box 28 45000 vs line Σ 450 must defer, not preserve."""
    lines = [{"charges": "450.00"}]
    assert is_decimal_place_shift("45000.00", "450.00")
    assert should_defer_box28_to_line_sum("45000.00", lines)
    # Place-shift rivals stay CONFLICT-eligible (not ratio-ignored), but defer wins.
    assert not is_implausible_corroborator("45000.00", "450.00")


def test_same_stem_cents_twin_box28_corroborates_line_sum():
    """157.07 beside Σ 157.00 is OCR twin noise — corroborate, do not CONFLICT."""
    from packages.claim_evidence.line_sum_authority import (
        amounts_corroborate_or_cents_twin,
        amounts_same_stem_cents_twin,
    )

    assert amounts_same_stem_cents_twin("157.00", "157.07")
    assert amounts_corroborate_or_cents_twin("157.00", "157.07")
    assert not amounts_corroborate("157.00", "157.07")

    lines = [
        {
            "charges": "157.00",
            "producing_engine": "paddleocr",
            "candidates": [
                {"value": "157.00", "engine": "paddleocr", "source_crop_id": "l1"},
                {
                    "value": "157.00",
                    "engine": "azure_gpt4o_crop",
                    "source_crop_id": "g1",
                },
            ],
        }
    ]
    ok, reason = line_sum_auto_eligible(lines, box28_value="157.07")
    assert ok and reason == "SINGLE_LINE_GPT4O_LOCAL"

    # True near-miss dollars still CONFLICT.
    ok, reason = line_sum_auto_eligible(lines, box28_value="222.00")
    assert not ok and reason == "BOX28_OR_DI_CONFLICT"


def test_blind50_multiline_digit_drop_restores_stp_single_line_stays_closed():
    from packages.claim_evidence.line_charge_selector import apply_line_charge_selector

    lines = apply_line_charge_selector(
        [
            {
                "charges": "185.00",
                "candidates": [
                    {"value": "185.00", "engine": "anthropic_claude_crop"},
                    {"value": "1851.00", "engine": "rapidocr"},
                ],
            },
            {
                "charges": "155.00",
                "candidates": [
                    {"value": "155.00", "engine": "anthropic_claude_crop"},
                    {"value": "1551.00", "engine": "rapidocr"},
                ],
            },
        ]
    )
    ok, reason = line_sum_auto_eligible(lines)
    assert ok and reason == "MULTI_LINE_DIGIT_DROP_FULLER_LOCAL"
    assert line_sum_total(lines) == "3402.00"

    single = apply_line_charge_selector(
        [
            {
                "charges": "13.00",
                "candidates": [
                    {"value": "13.00", "engine": "anthropic_claude_crop"},
                    {"value": "131.00", "engine": "rapidocr"},
                ],
            }
        ]
    )
    ok, reason = line_sum_auto_eligible(single)
    assert not ok and reason == "SINGLE_LINE_REQUIRES_DI"



def test_digit_drop_box28_underread_unlocks_fuller_line_sum():
    """DJKN.004/007: Box 28 200 under-reads DIGIT_DROP_FULLER line 2001."""
    from packages.claim_evidence.line_sum_authority import (
        box28_digit_drop_underread_of_fuller_line,
        line_sum_auto_eligible,
        should_defer_box28_to_line_sum,
    )

    lines = [
        {
            "charges": "2001.00",
            "line_charge_selection": {
                "disposition": "SELECTED_LOCAL_CHARGE",
                "amount": "2001.00",
                "reason": "DIGIT_DROP_FULLER_LOCAL",
            },
        }
    ]
    assert box28_digit_drop_underread_of_fuller_line("200.00", lines)
    assert should_defer_box28_to_line_sum("200.00", lines)
    ok, reason = line_sum_auto_eligible(
        lines, box28_value="200.00", corroborating_values=["200.00", "2004.00"]
    )
    assert ok and reason == "DIGIT_DROP_BOX28_UNDERREAD"
    # After deferral, whitelist extension alone must not re-arm CONFLICT.
    ok, reason = line_sum_auto_eligible(
        lines, box28_value=None, corroborating_values=["2004.00"]
    )
    assert ok and reason == "DIGIT_DROP_BOX28_UNDERREAD"
    # Bare single-line digit-drop without Box 28 under-read stays closed.
    ok, reason = line_sum_auto_eligible(lines, box28_value=None, corroborating_values=[])
    assert not ok


def test_geometry_cents_line_supports_box28_over_dollars_truncation():
    """DJKH.037: GEOMETRY_CENTS 1291.15 supports Box 28 vs dollars 129."""
    from packages.claim_evidence.line_sum_authority import (
        llm_charge_pick_has_open_source_authority,
    )

    lines = [
        {
            "charges": "1291.15",
            "candidates": [
                {
                    "engine": "rapidocr",
                    "value": "1291.15",
                    "preprocessing_variant": "GEOMETRY_CENTS",
                },
                {
                    "engine": "paddleocr",
                    "value": "129.00",
                    "preprocessing_variant": "CURRENCY_DECIMAL_V2|dollars_ruling",
                },
                {
                    "engine": "rapidocr",
                    "value": "129.00",
                    "preprocessing_variant": "CURRENCY_DECIMAL_V2|dollars_ruling",
                },
            ],
            "attempts": [
                {
                    "engine": "rapidocr",
                    "reason": "GEOMETRY_CENTS",
                    "observation": {"shaped": "1291.15"},
                }
            ],
        }
    ]
    cands = [
        {"engine": "anthropic_claude_crop", "value": "1291.15"},
        {"engine": "paddleocr", "value": "115.00"},
        {"engine": "rapidocr", "value": "129.00"},
    ]
    assert llm_charge_pick_has_open_source_authority("1291.15", cands, lines)
    # Without geometry cents, inflated 1291 vs local 129 stays unauthorized.
    assert not llm_charge_pick_has_open_source_authority(
        "1291.15", cands, [{"charges": "129.00", "candidates": cands}]
    )


def test_prefer_open_source_digit_drop_fuller_box28():
    """DJKN.005 prefers paddle 2001; DJKN.001 keeps 200 when paddle agrees."""
    from packages.claim_evidence.line_sum_authority import (
        agent_amount_is_inflated_scale,
        llm_charge_pick_has_open_source_authority,
        prefer_open_source_digit_drop_fuller_box28,
    )

    djkn005 = [
        {"engine": "azure_document_intelligence_read", "value": "200.00"},
        {"engine": "anthropic_claude_crop", "value": "200.00"},
        {
            "engine": "paddleocr",
            "value": "2001.00",
            "raw_value": "200100",
            "preprocessing_variant": "charge_digit_whitelist_fast:full",
        },
    ]
    assert prefer_open_source_digit_drop_fuller_box28("200.00", djkn005) == "2001.00"
    # 2001/200 ≈ ×10 trips inflated-scale, but unique OS digit-drop fuller wins.
    assert agent_amount_is_inflated_scale("2001.00", djkn005)
    assert llm_charge_pick_has_open_source_authority("2001.00", djkn005)
    # Short DI/Claude under-read stays unauthorized (no exact OS 200).
    assert not llm_charge_pick_has_open_source_authority("200.00", djkn005)
    # DJKN.001: local also reads 200 — do not override.
    djkn001 = [
        {"engine": "azure_document_intelligence_read", "value": "200.00"},
        {
            "engine": "paddleocr",
            "value": "200.00",
            "preprocessing_variant": "charge_digit_whitelist_fast:full",
        },
        {
            "engine": "rapidocr",
            "value": "2001.00",
            "preprocessing_variant": "GEOMETRY_CENTS",
        },
    ]
    assert prefer_open_source_digit_drop_fuller_box28("200.00", djkn001) is None
    # Real DJKN.001: paddle whitelist agrees with DI — no OS fuller rival.
    djkn001_auth = [
        {"engine": "azure_document_intelligence_read", "value": "200.00"},
        {
            "engine": "paddleocr",
            "value": "200.00",
            "preprocessing_variant": "charge_digit_whitelist_fast:full",
        },
    ]
    assert llm_charge_pick_has_open_source_authority("200.00", djkn001_auth)


def test_geometry_underread_whole_dollar_box28_djkn009():
    """DJKN.009: UNDERREAD raw 600 → 600.00; soup line 1600 is not a rival."""
    from packages.claim_evidence.line_sum_authority import (
        box28_geometry_underread_whole_dollar,
        charge_conflicts_with_plausible_line_sum,
        llm_charge_pick_has_open_source_authority,
    )

    payload = {
        "ocr": {
            "attempts": [
                {
                    "engine": "rapidocr",
                    "reason": "GEOMETRY_CENTS_UNDERREAD",
                    "observation": {
                        "text": "600",
                        "raw_digit_sequence": "600",
                        "shaped": "6.00",
                        "canonical_monetary_value": "6.00",
                        "dollar_glyphs": ["6"],
                        "cents_glyphs": ["0", "0"],
                        "adopted": False,
                    },
                }
            ],
            "candidates": [],
        }
    }
    assert box28_geometry_underread_whole_dollar(payload) == "600.00"
    lines = [
        {
            "charges": "1600.00",
            "line_charge_selection": {
                "disposition": "AMBIGUOUS_LINE_CHARGE",
                "amount": "1600.00",
                "reason": "ONLY_BLEED_OR_SOUP_CANDIDATES",
                "rejected": [{"value": "1600.00", "reason": "BARE_DIGIT_SOUP"}],
            },
        }
    ]
    cands = [
        {
            "engine": "paddleocr",
            "value": "60.00",
            "raw_value": "6000",
            "preprocessing_variant": "charge_digit_whitelist_fast:full",
        },
        {
            "engine": "rapidocr",
            "value": "600.00",
            "preprocessing_variant": "GEOMETRY_CENTS",
        },
        {"engine": "azure_document_intelligence_read", "value": "160.00"},
    ]
    assert not charge_conflicts_with_plausible_line_sum("600.00", lines, cands)
    assert llm_charge_pick_has_open_source_authority("600.00", cands, lines)
