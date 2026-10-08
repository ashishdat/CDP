from packages.extraction_recovery.span_selection import select_field_span

def test_observed_suffix_not_discarded_or_substituted():
    result=select_field_span('1004896283/305150','ALPHANUMERIC_ID','insured_id_number')
    assert result.selected_text=='1004896283/305150'
    assert result.selected_text!='1004896283V305150'

def test_caption_strip_preserves_slash_suffix():
    result=select_field_span("1a. INSURED'S I.D. NUMBER (For Program In Item.1) 1004896283/305150",'ALPHANUMERIC_ID','insured_id_number')
    assert result.selected_text=='1004896283/305150'

def test_date_not_reinterpreted_as_slash_identifier():
    result=select_field_span('09/23/1941','ALPHANUMERIC_ID','insured_id_number')
    assert result.rule_id != 'span-v1-member-id'
