"""Vision-only field proposals with explicit provenance and a review gate.

Provider confidence is not OCR confidence or measured field accuracy. A crop
reading can assist review without satisfying the extraction acceptance contract.
"""
import math
import re
from pathlib import Path

from workers.unstructured_extraction.uat_evidence import date_role
from workers.unstructured_extraction.uat_recovery_rules import name_key, name_similarity
from workers.unstructured_extraction.uat_validation import valid_scalar
from workers.unstructured_extraction.uat_values import DATE_FIELDS, date_value, identity_value

ALLOWED_FIELDS = {'patient_name', *DATE_FIELDS, 'identity_number', 'identity_number_masked',
                  'license_number', 'ecg_interpretation', 'tmt_interpretation'}
INTERPRETATION = {'ecg_interpretation', 'tmt_interpretation'}


def crop_valid(box):
    return (isinstance(box, (list, tuple)) and len(box) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in box)
            and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1
            and (box[2]-box[0])*(box[3]-box[1]) <= .5)


def propose(field, result, *, record, asset, evidence_path, authorized_job):
    """Never invent an OCR witness or replace source spelling with a reference.

    The job is a trusted local allowlist, not instructions supplied by a model.
    Its field role/crop must have been localized before the request was sent.
    """
    name = field.get('field_name'); value = field.get('value')
    issues = []
    if result.get('status') != 'SUCCESS' or field.get('insufficient_evidence') or not value:
        return None
    if not isinstance(value, str):
        return None
    if name not in ALLOWED_FIELDS or name not in authorized_job.get('fields', {}):
        issues.append('FIELD_NOT_ALLOWLISTED')
    box = result.get('crop_fraction')
    if not crop_valid(box) or box != authorized_job.get('crop_fraction'):
        issues.append('INVALID_OR_UNBOUND_CROP')
    if (not result.get('source_image') or Path(result['source_image']).resolve() != Path(asset['path']).resolve()
            or Path(authorized_job.get('image', '')).resolve() != Path(asset['path']).resolve()):
        issues.append('SOURCE_IMAGE_MISMATCH')
    if not evidence_path or not asset.get('sha256'):
        issues.append('SOURCE_PROVENANCE_MISSING')
    if not valid_scalar(name, value):
        issues.append('INVALID_FORMAT_OR_LABEL_TEXT')
    citation = field.get('citation') or ''
    if not isinstance(citation, str) or not citation.strip():
        issues.append('MODEL_CITATION_MISSING')
        citation = ''
    if not authorized_job.get('localization_basis'):
        issues.append('FIELD_ROLE_UNCONFIRMED')
    corroboration = []
    field_corroboration = []
    if name == 'patient_name':
        if re.search(r"father(?:'s)?\s+name|mother(?:'s)?\s+name|doctor(?:'s)?\s+name|name\s+of\s+doctor", citation, re.IGNORECASE):
            issues.append('PARENT_OR_DOCTOR_IS_NOT_PATIENT')
        refs = [r for r in record.get('verified_name_sources', [])
                if r.get('document_id') and r['document_id'] != record['id'] and r.get('source_verified')
                and r.get('raw_confidence', 0) >= .8 and r.get('evidence_reference')]
        corroboration = [r for r in refs if name_similarity(value, r['value']) >= .9]
        if refs and not corroboration:
            issues.append('OTHER_DOCUMENT_NAME_MISMATCH')
        if corroboration:
            exact = any(re.sub('[^a-z]', '', name_key(value)) == re.sub('[^a-z]', '', name_key(r['value']))
                        for r in corroboration)
            if not exact:
                issues.append('FUZZY_MATCH_SPELLING_REQUIRES_REVIEW')
    elif name in DATE_FIELDS:
        parsed = date_value(value)
        if parsed['year_ambiguous']:
            issues.append('AMBIGUOUS_DATE_YEAR')
        role = date_role(citation.split(value)[0])
        if role and role != name:
            issues.append('SOURCE_DATE_ROLE_MISMATCH')
        # Dates on different tests are not interchangeable corroborators.
    elif name == 'identity_number':
        if re.search(r'\bVID\b|virtual\s+id', citation, re.IGNORECASE):
            issues.append('VID_IS_NOT_IDENTITY_NUMBER')
        masked = record.get('masked_candidates', [])
        if identity_value(value)['kind'] == 'full_aadhaar' and masked:
            issues.append('FULL_NUMBER_FROM_MASKED_SOURCE_FORBIDDEN')
    elif name in INTERPRETATION:
        if re.search(r'infer(?:red)?|based on (?:the )?(?:waveform|trace)|appears to (?:be|show)', citation, re.IGNORECASE):
            issues.append('INFERRED_CLINICAL_INTERPRETATION_FORBIDDEN')
    # Only stable identity attributes are cross-document corroborators. The
    # dates/conclusions of different medical tests must never fill each other.
    if name in {'patient_dob', 'identity_number', 'license_number'}:
        refs = [r for r in record.get('verified_field_sources', []) if r.get('field_name') == name
                and r.get('document_id') != record['id'] and r.get('document_id')
                and r.get('source_verified') and r.get('raw_confidence', 0) >= .8 and r.get('evidence_reference')]
        if name == 'identity_number':
            refs = [r for r in refs if identity_value(r['value'])['kind'] == identity_value(value)['kind']]
        def canonical(v):
            return (date_value(v)['canonical_value'] if name == 'patient_dob'
                    else re.sub(r'[^A-Z0-9]', '', v.upper()))
        field_corroboration = [r for r in refs if canonical(value) and canonical(value) == canonical(r['value'])]
        if refs and not field_corroboration and (name != 'patient_dob' or not date_value(value)['year_ambiguous']):
            issues.append('OTHER_DOCUMENT_IDENTITY_ATTRIBUTE_MISMATCH')
    hard = [i for i in issues if i not in {'FUZZY_MATCH_SPELLING_REQUIRES_REVIEW', 'AMBIGUOUS_DATE_YEAR', 'FIELD_ROLE_UNCONFIRMED'}]
    status = ('REJECTED' if hard else 'CORROBORATED_REVIEW_REQUIRED' if (corroboration or field_corroboration) and not issues
              else 'REVIEW_REQUIRED')
    bbox = (dict(zip(['x0', 'y0', 'x1', 'y1'], [box[0]*asset['width'], box[1]*asset['height'],
                    box[2]*asset['width'], box[3]*asset['height']], strict=True)) if crop_valid(box) else {})
    return {'field_name': name, 'value': value, 'vision_only': True,
            'raw_confidence': 0.0, 'ocr_confidence_available': False,
            'confidence_note': 'Zero is a conservative routing sentinel, not a measured OCR confidence.',
            'model_confidence': field.get('confidence'), 'model_confidence_is_accuracy': False,
            'engine': result.get('provider', 'vision_model'), 'field_association': 'VISION_ONLY_CROP_PROPOSAL',
            'page_number': asset['page'], 'bounding_box': bbox,
            'source_image': asset['path'], 'source_image_sha256': asset.get('sha256'), 'crop_fraction': box,
            'evidence_reference': str(evidence_path), 'model_citation': citation,
            'model_citation_is_source_verification': False, 'authorized_job_id': authorized_job.get('id'),
            'field_role_evidence': authorized_job.get('localization_basis', 'UNVERIFIED'),
            'corroborating_name_sources': corroboration, 'validation_issues': issues,
            'corroborating_field_sources': field_corroboration,
            'review_status': status, 'acceptance_gate': 'VISION_ONLY_ACCURACY_NOT_VALIDATED',
            'auto_accept_eligible': False}
