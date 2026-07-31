from workers.table_extraction.field_candidate_parsing import parsed_alternatives


def test_date_noise_deletion_is_calendar_validated_and_review_only():
    alternatives = parsed_alternatives("0729125", "date")
    repaired = next(row for row in alternatives if row["value"] == "07 29 25")
    assert repaired["automatically_acceptable"] is False
    assert repaired["method"] == "CALENDAR_VALIDATED_SINGLE_NOISE_DELETION"


def test_character_confusions_are_bounded_and_review_only():
    alternatives = parsed_alternatives("14", "numeric")
    repaired = next(row for row in alternatives if row["value"] == "11")
    assert repaired["automatically_acceptable"] is False
    assert repaired["reason"] == "AMBIGUOUS_OCR_REPAIR_REQUIRES_REVIEW"


def test_text_v_y_confusion_retains_review_only_lineage():
    alternatives = parsed_alternatives("ANCILLARV CODE DETOX", "text")
    repaired = next(row for row in alternatives if row["value"] == "ANCILLARYCODEDETOX")
    assert repaired["automatically_acceptable"] is False
