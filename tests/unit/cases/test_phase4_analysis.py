
import pytest

from evaluation.phase4_analysis import generate_reports
from evaluation.production_readiness import FRONTIER


@pytest.mark.skipif(
    not (FRONTIER / "manifest.json").is_file(),
    reason="private evidence_frontier_v2 artifacts not installed",
)
def test_phase4_analysis_is_truthful_and_preserves_frozen_decisions(tmp_path):
    result = generate_reports(docs=tmp_path)
    assert result["e5"]["non_stp_claims"] == 24
    assert result["e5"]["qualification"] == "COUNTERFACTUAL_ONLY_NO_E5_WAS_FABRICATED"
    assert sum(row["field_count"] for row in result["residual"]) == 85
    assert result["cost"]["documents"] == 120
    assert result["cost"]["fields"] == 600
    assert result["cost"]["cost_document_usd"] is None
    assert (tmp_path / "CDP_E5_STP_OPPORTUNITY.md").is_file()
