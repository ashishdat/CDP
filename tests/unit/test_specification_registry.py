from packages.specification_registry.parser import LegacyClaimSpecParser, picture_length
from packages.specification_registry.validator import validate_specification


def test_parser_preserves_positions_rules_and_calculated_length():
    text = """
Record Type: AA0 Record Name: Header
This record must precede all claims.
01.0 01 03 X(03) R RECORD ID - Must be AA0
02.0 04 06 9(03) C COUNT
Required when claims are present. Right justify, zero fill.
"""
    spec = LegacyClaimSpecParser().parse(
        text,
        format_name="nsf",
        version="1",
        source_document="test.doc",
        record_length=6,
    )
    assert spec.records[0].fields[0].calculated_length == 3
    assert spec.records[0].fields[1].conditional_rules
    assert not validate_specification(spec)


def test_picture_length_supports_implied_decimal():
    assert picture_length("9(03)V99") == 5
