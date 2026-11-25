from unittest.mock import patch

import pytest

from scripts.score_uat_review import score
from tests.unit.test_uat_extraction_acceptance import ASSETS, candidate, page
from workers.unstructured_extraction.extraction_acceptance import ExtractionAcceptance, normalized
from workers.unstructured_extraction.uat_cases import decide_case
from workers.unstructured_extraction.uat_localization import field_region
from workers.unstructured_extraction.uat_values import date_value, identity_value


def test_short_year_requires_same_field_full_year_evidence():
    assert date_value('27/06/26')['year_ambiguous']
    assert date_value('27/06/26', ['27/06/2026'])['canonical_value'] == '2026-06-27'
    assert date_value('27/06/26', ['27/06/1926', '27/06/2026'])['year_ambiguous']


def test_masked_number_cannot_supply_full_identifier():
    value = identity_value('XXXX XXXX 1234')
    assert value['kind'] == 'masked_aadhaar'
    assert value['canonical_value'] is None
    assert identity_value('1234')['kind'] == 'unresolved'


def test_weak_label_guess_does_not_conflict_with_bound_name():
    weak = dict(candidate('JOHN DOE'), field_association='WEAK_LABEL_GUESS')
    result = ExtractionAcceptance().decide('PATH', [page('BIOCHEMISTRY')], expected_pages=1,
        assets=ASSETS, candidates={'patient_name': [candidate('JANE DOE'), weak],
                                  'report_date': [candidate('29/06/2026')]})
    assert result['extraction_stp_eligible']
    assert result['field_diagnostics']['patient_name']['eligible_candidates'] == 1


def test_title_normalization_preserves_actual_name_prefixes():
    assert normalized('patient_name', 'Dr. Jane Doe') == normalized('patient_name', 'Jane Doe')
    assert normalized('patient_name', 'Dravid Kumar') != normalized('patient_name', 'avid Kumar')


def test_portrait_cannot_complete_declared_identity_role():
    result = decide_case([{'id': 'case/id', 'declared_type': 'AADHAAR', 'decision': {
        'extraction_stp_eligible': True, 'provided_roles': ['image_asset'], 'extracted_fields': {}}}])
    assert not result['case_complete']
    assert result['missing_roles'] == ['identity:aadhaar']


def test_label_localization_refuses_multiple_matches():
    from types import SimpleNamespace
    box = SimpleNamespace(x0=10, y0=20, x1=100, y1=40)
    line = SimpleNamespace(text='Patient name', bbox=box)
    assert field_region(SimpleNamespace(lines=[line, line]), ['patient name'], 500, 500) is None
    region = field_region(SimpleNamespace(lines=[line]), ['patient name'], 500, 500)
    assert region and all(0 <= value <= 1 for value in region)


def test_review_scorer_rejects_unreviewed_rows():
    text = 'document_id,field,reviewed,reviewer\ncase/doc,patient_name,False,\n'
    with patch('pathlib.Path.read_text', return_value=text), pytest.raises(ValueError, match='independent review'):
        score('labels.csv')
