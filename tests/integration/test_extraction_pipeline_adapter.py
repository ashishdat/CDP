"""Integration with existing normalization; synthetic cases, not benchmarks."""

import pytest

from packages.extraction_pipeline import FeatureFlag, FeatureFlags, PipelineContext
from packages.extraction_pipeline.adapter import LegacyCallableAdapter
from workers.standard_form_extraction.field_processors import normalize


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize(
    ("field_type", "observed"),
    [
        ("text", "  JANE   DOE  "),
        ("date", "01/02/2024"),
        ("date", "invalid"),
        ("currency", "$1,234.50"),
        ("currency", ""),
        ("npi", "1234567890"),
        ("tax_id", "12-3456789"),
        ("checkbox", "X"),
        ("code", "A 123"),
        ("unknown", " unchanged "),
    ],
)
def test_existing_normalizer_outputs_are_preserved(enabled, field_type, observed):
    flags = FeatureFlags(frozenset({FeatureFlag.PIPELINE_V3}) if enabled else frozenset())
    adapter = LegacyCallableAdapter(normalize)
    actual = adapter.invoke(PipelineContext("synthetic", flags), field_type, observed)
    assert actual == normalize(field_type, observed)
