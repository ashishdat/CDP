"""DOB acquisition completeness; this does not grant field acceptance."""
from packages.field_normalization import normalize_date
from packages.ocr.independence import independence_group
from datetime import date
from packages.ocr.evidence_eligibility import eligible_candidates, confirmation_eligible


def dob_component_conflicts(candidates, attempts):
    """Retain contradictions from a reader that could read only part of a DOB."""
    import re

    parsed = []
    for candidate in eligible_candidates(candidates):
        value, valid = normalize_date(str(candidate.get('value') or ''))
        if valid:
            year, month, day = (int(part) for part in value.split('-'))
            parsed.append({'MM': month, 'DD': day, 'YY': year})
    if not parsed:
        return []
    from packages.extraction_recovery.dob_azure_di_residual import _shape_dob_text
    conflicts = []
    for attempt in attempts or []:
        if not confirmation_eligible(attempt):
            continue
        if not str(attempt.get('engine') or '').strip():
            continue
        observation = attempt.get('observation') or {}
        parts = observation.get('parts') or {}
        mm, dd, yy = (str(parts.get(label) or '') for label in ('MM', 'DD', 'YY'))
        if re.fullmatch(r'\d{2}', mm) and re.fullmatch(r'\d{2}', dd) and re.fullmatch(r'(?:\d{2}|\d{4})', yy):
            full, observed = _shape_dob_text('patient_dob', f'{mm} {dd} {yy}', allow_ordered_components=True)
            if observed:
                normalized, valid = normalize_date(full or '')
                if valid:
                    year, month, day = (int(part) for part in normalized.split('-'))
                    if {'MM': month, 'DD': day, 'YY': year} in parsed:
                        continue  # Only a retained complete date has normal conflict handling.
        for label, raw in parts.items():
            digits = str(raw or '')
            if label in {'MM', 'DD'}:
                upper = 12 if label == 'MM' else 31
                if not re.fullmatch(r'\d{2}', digits) or not 1 <= int(digits) <= upper:
                    continue
                contradicted = all(item[label] != int(digits) for item in parsed)
            elif label == 'YY':
                if re.fullmatch(r'\d{2}', digits):
                    contradicted = all(item[label] % 100 != int(digits) for item in parsed)
                elif re.fullmatch(r'\d{4}', digits) and 1900 <= int(digits) <= date.today().year:
                    contradicted = all(item[label] != int(digits) for item in parsed)
                else:
                    continue
            else:
                continue
            if contradicted:
                conflict = {'engine': attempt['engine'], 'component': label, 'observed': digits}
                if conflict not in conflicts:
                    conflicts.append(conflict)
    return conflicts


def dob_reads_confirmed(candidates, attempts=None):
    if dob_component_conflicts(candidates, attempts):
        return False
    dates = {}
    for candidate in eligible_candidates(candidates):
        engine = str(candidate.get('engine') or '').strip()
        if not engine:
            continue
        value, valid = normalize_date(str(candidate.get('value') or ''))
        if valid:
            dates.setdefault(value, set()).add(independence_group(engine))
    return len(dates) == 1 and len(next(iter(dates.values()))) >= 2
