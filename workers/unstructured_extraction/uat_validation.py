"""Scalar format checks; these do not establish identity or medical correctness."""
import re

from workers.unstructured_extraction.uat_values import (
    DATE_FIELDS,
    date_value,
    identity_value,
    label_only,
)


def valid_scalar(field, value):
    value = ' '.join(value.split()).strip(' :')
    if not value:
        return False
    if field in DATE_FIELDS:
        return date_value(value)['valid_format']
    if field == 'patient_name':
        label_prefixes=('doctor name ','registered on ','reported on ','collected on ',
                        'referred by ','full name of ','life assured ')
        return (not label_only(value) and not value.casefold().startswith(label_prefixes)
            and bool(re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,100}", value)) and 1<=len(value.split())<=8)
    if field == 'identity_number':
        return identity_value(value)['kind'] in {'full_aadhaar','full_pan'}
    if field == 'identity_number_masked':
        return identity_value(value)['kind'] == 'masked_aadhaar'
    if field=='license_number':
        # Recognized engineering format only; unsupported formats remain reviewable.
        return bool(re.fullmatch(r'[A-Z]{2}\d{13}',re.sub(r'[ -]','',value.upper())))
    if field in {'ecg_interpretation','tmt_interpretation'}:
        return len(value) >= 3 and any(character.isalpha() for character in value)
    return False
