"""Pure observed-word geometry for DOB; no provider clients or acceptance authority."""
import re
import math

def observed_numeric_word(text):
    """Remove only literal edge rulings; preserve all digits and other glyphs."""
    return str(text or '').strip().strip('|').strip()

def spatial_dob_components(words: tuple[dict, ...]) -> str | None:
    """Read one numeric word below each observed MM/DD/YY label, in physical order."""
    positions = []
    bounds = {}
    for word in words:
        polygon = word.get('polygon') or ()
        if len(polygon) != 8:
            continue
        try:
            xs, ys = [float(x) for x in polygon[::2]], [float(y) for y in polygon[1::2]]
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(v) for v in xs + ys) or max(xs) <= min(xs) or max(ys) <= min(ys):
            return None
        positions.append((observed_numeric_word(word.get('content')),
                          (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2,
                          max(ys) - min(ys)))
        bounds[positions[-1]] = (min(xs), max(xs))
    headers = {}
    for text, x, y, height in positions:
        label = text.upper().strip('.:')
        if label in {'MM', 'DD', 'YY', 'YYYY'}:
            key = 'YY' if label == 'YYYY' else label
            if key in headers:
                return None  # More than one header set is not one bound date.
            headers[key] = (x, y)
    if set(headers) != {'MM', 'DD', 'YY'}:
        # This is a bound DATE crop, not a full-page text search. Headers may
        # be unreadable; exactly three numeric words on one physical baseline
        # still retain observed MM, DD, YY order without guessing components.
        numeric = [(text, x, y, height) for text, x, y, height in positions
                   if re.fullmatch(r'[0-9]{2}|[0-9]{4}', text)]
        numeric.sort(key=lambda item: item[1])
        if len(numeric) != 3 or any(len(v[0]) != 2 for v in numeric[:2]):
            return None
        if max(v[2] for v in numeric) - min(v[2] for v in numeric) > max(v[3] for v in numeric):
            return None
        values = [(v[0], v[2], v[3]) for v in numeric]
        return _calendar_dob_from_components(values)
    mm, dd, yy = (headers[k][0] for k in ('MM', 'DD', 'YY'))
    if not mm < dd < yy:
        return None
    splits = ((mm + dd) / 2, (dd + yy) / 2)
    # DI sometimes merges physically adjacent MM and DD into one word,
    # e.g. observed "0130" beneath MM/DD plus "1965" beneath YY. Split
    # only the exact 2+2 grammar when its polygon spans both header columns.
    # Every digit is observed; a year in the left column cannot be reassigned.
    numeric_all = [p for p in positions if re.fullmatch(r"[0-9]+", p[0])]
    if len(numeric_all) == 2:
        merged = [p for p in numeric_all if len(p[0]) == 4
                  and bounds[p][0] <= mm and bounds[p][1] >= dd
                  and bounds[p][1] < splits[1] and p[2] > max(headers['MM'][1],headers['DD'][1])]
        years = [p for p in numeric_all if len(p[0]) in {2,4} and p[1] > splits[1]
                 and p[2] > headers['YY'][1]]
        if len(merged) == len(years) == 1:
            a,b = merged[0],years[0]
            if abs(a[2]-b[2]) <= max(a[3],b[3]):
                return _calendar_dob_from_components([(a[0][:2],a[2],a[3]),(a[0][2:],a[2],a[3]),(b[0],b[2],b[3])])
    cells = {k: [] for k in headers}
    for text, x, y, height in positions:
        if not re.fullmatch(r'[0-9]{2}|[0-9]{4}', text):
            continue
        key = 'MM' if x < splits[0] else 'DD' if x < splits[1] else 'YY'
        if y <= headers[key][1] or (key != 'YY' and len(text) != 2):
            continue
        cells[key].append((text, y, height))
    if any(len(values) != 1 for values in cells.values()):
        return None  # Never pick arbitrarily among rival observed components.
    values = [cells[k][0] for k in ('MM', 'DD', 'YY')]
    if max(v[1] for v in values) - min(v[1] for v in values) > max(v[2] for v in values):
        return None  # Different text lines cannot be joined into a date.
    return _calendar_dob_from_components(values)


def _calendar_dob_from_components(values) -> str | None:
    from datetime import date
    from packages.extraction_recovery.span_selection import select_field_span
    from packages.field_normalization import normalize_date

    if len(values[2][0]) == 4:
        # Never century-repair an explicitly observed four-digit year.
        text = '/'.join(v[0] for v in values)
    else:
        text = select_field_span(' '.join(v[0] for v in values), 'DATE', 'patient_dob').selected_text
    normalized, valid = normalize_date(text)
    if not valid or date.fromisoformat(normalized) > date.today():
        return None
    return date.fromisoformat(normalized).strftime('%m/%d/%Y')

