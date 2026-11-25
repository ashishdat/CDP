"""Regression checks for completing generic extraction without empty STP."""
from types import SimpleNamespace

import pytest

from workers.unstructured_extraction.local_completion import LocalLayoutCompletion


def page(family):
    return SimpleNamespace(schema_evidence=SimpleNamespace(schema_family=family),
                           candidates={}, engine='tesseract_psm_11')


def test_empty_unknown_document_requires_review():
    result = LocalLayoutCompletion().complete('empty', [page('UNKNOWN')])
    assert result['extraction_status'] == 'COMPLETED'
    assert not result['claim_decision']['stp_eligible']
    assert result['claim_decision']['disposition'] == 'CLAIM_REVIEW_REQUIRED'
    assert 'NO_EXTRACTED_FIELDS' in result['completion_reason_codes']


def test_inferred_schema_without_acceptance_contract_cannot_stp():
    result = LocalLayoutCompletion().complete('medical', [page('MEDICAL_INVOICE')])
    assert 'DOCUMENT_ACCEPTANCE_SCHEMA_NOT_CONFIGURED' in result['completion_reason_codes']
    assert not result['claim_decision']['stp_eligible']


def test_conflicting_page_schemas_require_review():
    result = LocalLayoutCompletion().complete('mixed', [page('EOB'), page('MEDICAL_INVOICE')])
    assert result['document_family'] == 'UNKNOWN'
    assert 'DOCUMENT_SCHEMA_UNRESOLVED' in result['completion_reason_codes']
    assert not result['claim_decision']['stp_eligible']


def test_configured_mandatory_fields_are_decided_even_when_missing():
    completion = LocalLayoutCompletion()
    required = completion.services.field_policy.required_fields('CMS1500')
    assert required
    result = completion.complete('missing', [page('CMS1500')])
    assert {f['field_name'] for f in result['field_decisions']} == set(required)
    assert not result['claim_decision']['stp_eligible']


def test_no_pages_is_a_processing_error():
    with pytest.raises(ValueError, match='At least one'):
        LocalLayoutCompletion().complete('missing', [])
