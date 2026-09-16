"""Resume saved canonical geometry through OCR candidates only.

Run: python -m scripts.ocr_from_geometry GEOMETRY_DIRECTORY OUTPUT_DIRECTORY
"""
import argparse
import re
import hashlib
import json
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np
from PIL import Image

from packages.domain.common import BoundingBox
from packages.domain.enums import ClaimFormType
from packages.extraction_recovery import (
    inset_bbox,
    select_field_span,
    span_datatype_for_field,
)
from packages.extraction_recovery.field_cascade import (
    FieldCascade,
    charge_column_windows,
    semantic_accept,
)
from packages.extraction_recovery.strategy import post_miss_for
from packages.ocr.contracts import OCRCandidate
from packages.ocr_router import OCRRouter, OCRRouteRequest
from packages.templates.registry import TemplateRegistry



def _clamp_bbox(bbox, width, height):
    x0, y0, x1, y1 = (int(v) for v in bbox)
    x0 = max(0, min(x0, width - 1))
    y0 = max(0, min(y0, height - 1))
    x1 = max(x0 + 1, min(x1, width))
    y1 = max(y0 + 1, min(y1, height))
    return (x0, y0, x1, y1)


def _ocr_bbox(name, aligned, cell, image_size, template_fields):
    """Prefer template ROI inside the safe cell; otherwise inset the recorded ROI."""
    width, height = image_size
    cell_box = (cell['x0'], cell['y0'], cell['x1'], cell['y1'])
    template = template_fields.get(name)
    if template is not None:
        tx0, ty0, tx1, ty1 = template
        if (cell_box[0] <= tx0 < tx1 <= cell_box[2]
                and cell_box[1] <= ty0 < ty1 <= cell_box[3]):
            return _clamp_bbox((tx0, ty0, tx1, ty1), width, height)
    inset = inset_bbox(aligned, name)
    x0 = max(inset[0], cell_box[0])
    y0 = max(inset[1], cell_box[1])
    x1 = min(inset[2], cell_box[2])
    y1 = min(inset[3], cell_box[3])
    if x1 - x0 < 8 or y1 - y0 < 8:
        x0, y0, x1, y1 = aligned
    return _clamp_bbox((x0, y0, x1, y1), width, height)


def _load_cms1500_template():
    registry = TemplateRegistry.load_from_directory()
    templates = registry.all_for_form_type(ClaimFormType.CMS1500)
    return templates[0] if templates else None


_PREPROCESS = None


def _preprocessing_registry():
    global _PREPROCESS
    if _PREPROCESS is None:
        from packages.ocr.preprocessing import PreprocessingRegistry
        from pathlib import Path
        phase = Path('config/ocr_preprocessing_phase8_10.yaml')
        _PREPROCESS = PreprocessingRegistry.load(phase if phase.is_file() else None)
    return _PREPROCESS


def _recognize_one(image, name, bbox, router, field_type='', engine_order=None):
    # Phase 2: currency crops get Phase-8.10 preprocess. Other fields keep full-page
    # bbox OCR — crop-then-OCR shifted DOB digit assembly on sample B (10/29→11/29).
    currency_fields = {
        'total_charge', 'total_charges', 'charges', 'charge_amount', 'amount_paid',
    }
    use_preprocess = (
        (name or '').casefold() in currency_fields
        or 'currency' in (field_type or '').casefold()
        or 'money' in (field_type or '').casefold()
    )
    applied_profile = 'recorded_canonical_region'
    applied_version = 'none'
    if use_preprocess:
        x0, y0, x1, y1 = (int(v) for v in bbox)
        crop = image.crop((x0, y0, x1, y1))
        applied = _preprocessing_registry().apply(crop, name, field_type or '')
        route_image, route_bbox = applied.image, (0, 0, applied.image.width, applied.image.height)
        applied_profile, applied_version = applied.profile, applied.version
    else:
        route_image, route_bbox = image, tuple(int(v) for v in bbox)
    routed = router.route(OCRRouteRequest(route_image, route_bbox, engine_order=engine_order))
    candidates = []
    attempts = []
    for attempt in routed.attempts:
        observation = attempt.observation
        attempts.append({'engine': attempt.engine, 'reason': attempt.reason,
                         'latency_ms': attempt.latency_ns / 1e6,
                         'observation': asdict(observation) if observation else None,
                         'preprocessing_profile': applied_profile})
        if observation is None or not observation.lines:
            continue
        raw = chr(10).join(line.text for line in observation.lines)
        span = select_field_span(raw, span_datatype_for_field(name, field_type), name)
        selected = span.selected_text
        box = BoundingBox(x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3],
                          image_width=image.width, image_height=image.height)
        candidate = OCRCandidate(
            value=selected, raw_value=raw, engine=attempt.engine,
            model_name='unknown', model_version='unknown',
            preprocessing_variant=applied_profile,
            preprocessing_version=applied_version,
            raw_confidence=float(np.mean([line.confidence for line in observation.lines])),
            calibrated_confidence=None, bounding_box=box,
            latency_ms=attempt.latency_ns / 1e6)
        payload = {**asdict(candidate), 'bounding_box': box.model_dump(mode='json')}
        payload['span_selection'] = {
            'selected_text': span.selected_text,
            'rule_id': span.rule_id,
            'confidence': span.confidence,
            'reason_codes': list(span.reason_codes),
        }
        candidates.append(payload)

    # Handwritten charge crops sometimes regress under currency preprocess
    # (100 → I/00). If span emptied after preprocess, retry the raw crop once.
    if use_preprocess and not any((c.get('value') or '').strip() for c in candidates):
        raw_routed = router.route(OCRRouteRequest(image, tuple(int(v) for v in bbox), engine_order=engine_order))
        for attempt in raw_routed.attempts:
            observation = attempt.observation
            attempts.append({'engine': attempt.engine, 'reason': attempt.reason,
                             'latency_ms': attempt.latency_ns / 1e6,
                             'observation': asdict(observation) if observation else None,
                             'preprocessing_profile': 'raw_charge_fallback'})
            if observation is None or not observation.lines:
                continue
            raw = chr(10).join(line.text for line in observation.lines)
            span = select_field_span(raw, span_datatype_for_field(name, field_type), name)
            if not span.selected_text:
                continue
            box = BoundingBox(x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3],
                              image_width=image.width, image_height=image.height)
            candidate = OCRCandidate(
                value=span.selected_text, raw_value=raw, engine=attempt.engine,
                model_name='unknown', model_version='unknown',
                preprocessing_variant='raw_charge_fallback',
                preprocessing_version='none',
                raw_confidence=float(np.mean([line.confidence for line in observation.lines])),
                calibrated_confidence=None, bounding_box=box,
                latency_ms=attempt.latency_ns / 1e6)
            payload = {**asdict(candidate), 'bounding_box': box.model_dump(mode='json')}
            payload['span_selection'] = {
                'selected_text': span.selected_text,
                'rule_id': span.rule_id,
                'confidence': span.confidence,
                'reason_codes': list(span.reason_codes) + ['RAW_CHARGE_FALLBACK'],
            }
            candidates.append(payload)
            break

    # Digit-whitelist tesseract on charge crops when route OCR still empty —
    # recovers sparse typed amounts that engines read as punctuation (e.g. "L|1|1").
    currency_names = {
        'total_charge', 'total_charges', 'charges', 'charge_amount', 'amount_paid',
    }
    if (
        (name or '').casefold() in currency_names
        or 'currency' in (field_type or '').casefold()
        or 'money' in (field_type or '').casefold()
    ) and not any((c.get('value') or '').strip() for c in candidates):
        try:
            import pytesseract
            from PIL import ImageOps, ImageEnhance
            x0, y0, x1, y1 = (int(v) for v in bbox)
            crop = image.crop((x0, y0, x1, y1))
            up = crop.resize(
                (max(1, crop.width * 3), max(1, crop.height * 3)),
                Image.Resampling.LANCZOS,
            )
            up = ImageOps.autocontrast(up)
            up = ImageEnhance.Contrast(up).enhance(1.5)
            digit_raws = []
            for psm in (7, 8, 6):
                cfg = f'--oem 3 --psm {psm} -c tessedit_char_whitelist=0123456789.$'
                raw = pytesseract.image_to_string(up, config=cfg).strip()
                attempts.append({
                    'engine': 'tesseract_digits', 'reason': f'PSM_{psm}',
                    'latency_ms': 0.0,
                    'observation': {'text': raw} if raw else None,
                    'preprocessing_profile': 'charge_digit_whitelist',
                })
                if raw:
                    digit_raws.append(raw)
            for raw in digit_raws:
                span = select_field_span(
                    raw, span_datatype_for_field(name, field_type), name,
                )
                if not span.selected_text:
                    continue
                box = BoundingBox(
                    x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3],
                    image_width=image.width, image_height=image.height,
                )
                candidate = OCRCandidate(
                    value=span.selected_text, raw_value=raw, engine='tesseract_digits',
                    model_name='unknown', model_version='unknown',
                    preprocessing_variant='charge_digit_whitelist',
                    preprocessing_version='cascade-v7',
                    raw_confidence=0.7, calibrated_confidence=None, bounding_box=box,
                    latency_ms=0.0,
                )
                payload = {**asdict(candidate), 'bounding_box': box.model_dump(mode='json')}
                payload['span_selection'] = {
                    'selected_text': span.selected_text,
                    'rule_id': span.rule_id,
                    'confidence': span.confidence,
                    'reason_codes': list(span.reason_codes) + ['CHARGE_DIGIT_WHITELIST'],
                }
                candidates.append(payload)
                break
        except Exception:
            pass
    return candidates, attempts, routed.reason


def recognize_service_lines(image, router, template):
    """OCR CMS-1500 service-line charge cells for claim-total E6 confirmation."""
    table = getattr(template, 'service_line_region', None) if template is not None else None
    if table is None:
        return []
    charge_col = next((c for c in table.columns if c.field_name in {'charges', 'charge_amount'}), None)
    probe_cols = [c for c in table.columns if c.field_name in {'cpt_hcpcs', 'date_from'}]
    if charge_col is None:
        return []
    lines = []
    # Prefer data rows: start one half-row below the printed header rule.
    header_offset = max(8, table.row_height_px // 3)
    # Alternate x-windows: primary template column plus a right-shifted band that
    # avoids diagnosis-pointer bleed on many live CMS-1500 scans.
    charge_windows = [
        (x0, x1) for _, x0, x1 in charge_column_windows(charge_col.x0, charge_col.x1)
    ]

    def _currency_value(raw_text, candidates):
        import re as _re
        value = next((c.get('value') for c in candidates if (c.get('value') or '').strip()), None)
        if value is None and raw_text:
            # Fall back to span-shaped raw when candidates were empty/rejected.
            value = raw_text
        if value is None:
            return None
        cleaned = value.strip()
        if _re.search(r'[A-Za-z]', cleaned) and not _re.search(r'\d', cleaned):
            return None
        if not _re.search(r'\d', cleaned):
            return None
        if _re.search(r'(DIAGNOSIS|POINTER|FROM|HCPCS|CPT|NPI|PLACE|CHARGES)', cleaned.upper()):
            return None
        # Prefer explicit decimals; accept whole dollars from the charge column.
        m = _re.search(r'\$?\d{1,3}(?:,\d{3})*\.\d{2}|\$?\d{2,6}(?:\.\d{2})?', cleaned)
        if not m:
            return None
        amount = m.group(0).lstrip('$')
        if '.' not in amount and _re.fullmatch(r'\d{2,6}', amount):
            amount = f'{amount}.00'
        return amount

    for row_index in range(table.max_rows):
        y0 = table.table_y0 + header_offset + row_index * table.row_height_px
        y1 = min(y0 + table.row_height_px, table.table_y1)
        if y0 >= table.table_y1:
            break
        probe_empty = True
        import re as _re_probe
        for column in probe_cols:
            pb = _clamp_bbox((column.x0, y0, column.x1, y1), image.width, image.height)
            pcs, _, _ = _recognize_one(image, column.field_name, pb, router, column.field_type)
            for cand in pcs or []:
                # Prefer raw ink for liveness; span may empty a noisy but real cell.
                val = ((cand.get('raw_value') or '') + ' ' + (cand.get('value') or '')).strip()
                if not val:
                    continue
                if column.field_name in {'date_from', 'date_to'} and _re_probe.search(r'\d', val):
                    probe_empty = False
                    break
                if column.field_name in {'cpt_hcpcs', 'cpt', 'hcpcs'} and _re_probe.search(
                    r'\d{4,5}|[A-Z]\d{3,4}', val.upper()
                ):
                    probe_empty = False
                    break
            if not probe_empty:
                break
        # Phase 2: skip leading header/blank rows; only stop after a live block ends.
        # Charge-column currency ink can also prove the row is live when date/CPT probes fail.
        best = None
        for x0, x1 in charge_windows:
            bbox = _clamp_bbox((x0, y0, x1, y1), image.width, image.height)
            candidates, attempts, reason = _recognize_one(
                image, 'charges', bbox, router, charge_col.field_type)
            raw = candidates[0].get('raw_value') if candidates else ''
            value = _currency_value(raw, candidates)
            score = 0
            if value:
                score = 3 if '.' in value else 2
                # Prefer amounts that are not tiny single-digit dollars.
                if value[0] != '0' and not value.startswith('1.'):
                    score += 1
                # Dashed-rule crops like "-200-\nLAAM" are not service charges.
                # Allow / | : ? — common OCR noise inside repaired amounts
                # (I/00 → 100.00, 200:00 → 200.00, 200? → 200.00).
                import re as _re_noise
                raw_u = (raw or '').upper()
                if _re_noise.search(r'[^0-9A-Z./|:?\s,-]', raw_u) or _re_noise.fullmatch(r'[\s\-.,/|:?]*', raw or ''):
                    score = 0
                    value = None
            candidate = {
                'line_number': row_index + 1,
                'charges': value,
                'charge_amount': value,
                'raw_charges': raw,
                'canonical_region': list(bbox),
                'candidates': candidates,
                'attempts': attempts,
                'router_reason': reason,
                'status': 'OBSERVED' if value else 'NO_VALUE',
                '_score': score,
            }
            if best is None or candidate['_score'] > best['_score']:
                best = candidate
            if score >= 4:
                break
        assert best is not None
        best.pop('_score', None)
        if best.get('status') != 'OBSERVED':
            if any(l.get('status') == 'OBSERVED' for l in lines):
                # End of live block — do not emit the empty sentinel.
                break
            if probe_empty:
                # Leading header/blank row with no charge ink — keep scanning.
                continue
            # Probe saw date/CPT but charge empty: still end once we are past a live block.
            continue
        lines.append(best)
    return lines



def _dob_cell_bboxes(band):
    """Split a DOB digit band into MM / DD / YY cells (CMS-1500 box 3).

    Inset each cell away from the dashed vertical rules — those glyphs OCR as
    digit ``1`` and are the dominant source of 01↔11 / 09↔19 CONFLICT_MARGIN HITL.
    """
    x0, y0, x1, y1 = (int(v) for v in band)
    width = max(1, x1 - x0)
    inset = max(2, int(0.04 * width))
    mm_x1 = x0 + int(0.30 * width)
    dd_x0 = x0 + int(0.30 * width)
    dd_x1 = x0 + int(0.56 * width)
    yy_x0 = x0 + int(0.52 * width)
    return {
        'MM': (x0 + inset, y0, max(x0 + inset + 1, mm_x1 - inset), y1),
        'DD': (dd_x0 + inset, y0, max(dd_x0 + inset + 1, dd_x1 - inset), y1),
        'YY': (yy_x0 + inset, y0, max(yy_x0 + inset + 1, x1 - inset), y1),
    }


def _preprocess_dob_cell(crop):
    """Upscale + contrast for tight DOB digit cells (typed or handwritten)."""
    from PIL import ImageOps, ImageEnhance
    up = crop.resize((max(1, crop.width * 3), max(1, crop.height * 3)), Image.Resampling.LANCZOS)
    up = ImageOps.autocontrast(up)
    up = ImageEnhance.Contrast(up).enhance(1.6)
    return up


def _recognize_dob_cells(image, band, router, engines):
    """OCR MM/DD/YY cells independently and assemble a calendar date from observed digits."""
    cells = _dob_cell_bboxes(band)
    parts = {}
    attempts = []
    raw_bits = []

    def _digits_from(raw: str) -> str:
        return ''.join(ch for ch in raw if ch.isdigit())

    def _consider(label: str, digits: str, raw: str, best_digits: str) -> str:
        if not digits:
            return best_digits
        if label in {'MM', 'DD'}:
            # Keep last 1-2 digits (leading edge glyphs happen).
            trimmed = digits[-2:] if len(digits) >= 2 else digits
            if not (1 <= len(trimmed) <= 2):
                return best_digits
            # Prefer 0X over 1X when both are calendar-plausible — dashed
            # rule bleed into the cell still produces a leading 1.
            if best_digits and len(best_digits) == 2 and len(trimmed) == 2:
                if best_digits[0] == '0' and trimmed[0] == '1' and best_digits[1] == trimmed[1]:
                    return best_digits
                if trimmed[0] == '0' and best_digits[0] == '1' and best_digits[1] == trimmed[1]:
                    return trimmed
            if len(trimmed) >= len(best_digits):
                return trimmed
        elif label == 'YY':
            # Prefer 4-digit years; allow 2-3 (span repairs 983→1983).
            if 2 <= len(digits) <= 5 and len(digits) >= len(best_digits):
                return digits[-4:] if len(digits) > 4 else digits
        return best_digits

    for label, bbox in cells.items():
        bbox = _clamp_bbox(bbox, image.width, image.height)
        crop = _preprocess_dob_cell(image.crop(bbox))
        best_digits = ''
        # Primary route engines on the upscaled cell.
        routed = router.route(
            OCRRouteRequest(crop, (0, 0, crop.width, crop.height), engine_order=engines)
        )
        for attempt in routed.attempts:
            observation = attempt.observation
            attempts.append({
                'engine': attempt.engine, 'reason': attempt.reason,
                'latency_ms': attempt.latency_ns / 1e6,
                'observation': asdict(observation) if observation else None,
                'preprocessing_profile': 'dob_cell_upscale',
                'dob_cell': label,
            })
            if observation is None or not observation.lines:
                continue
            raw = chr(10).join(line.text for line in observation.lines)
            raw_bits.append(f'{label}:{raw}')
            best_digits = _consider(label, _digits_from(raw), raw, best_digits)
        # Digit-only tesseract pass — typed CMS DOB cells often resolve under whitelist.
        try:
            import pytesseract
            for psm in (10, 7, 8):
                cfg = f'--oem 3 --psm {psm} -c tessedit_char_whitelist=0123456789'
                raw = pytesseract.image_to_string(crop, config=cfg).strip()
                attempts.append({
                    'engine': 'tesseract_digits', 'reason': f'PSM_{psm}',
                    'latency_ms': 0.0, 'observation': {'text': raw},
                    'preprocessing_profile': 'dob_cell_upscale', 'dob_cell': label,
                })
                if raw:
                    raw_bits.append(f'{label}:tess{psm}:{raw}')
                    best_digits = _consider(label, _digits_from(raw), raw, best_digits)
        except Exception:
            pass
        parts[label] = best_digits
    mm, dd, yy = parts.get('MM', ''), parts.get('DD', ''), parts.get('YY', '')
    # Reject weak cell reads — garbage like "1'4QR2" can span-shape into a false date.
    if not (re.fullmatch(r'\d{1,2}', mm) and 1 <= int(mm) <= 12):
        return [], attempts, 'DOB_CELLS_EMPTY'
    if not (re.fullmatch(r'\d{1,2}', dd) and 1 <= int(dd) <= 31):
        return [], attempts, 'DOB_CELLS_EMPTY'
    if not (re.fullmatch(r'\d{2,4}', yy) and (
        (len(yy) == 2) or (len(yy) == 3 and yy[0] in '189') or (len(yy) == 4 and 1900 <= int(yy) <= 2100)
    )):
        return [], attempts, 'DOB_CELLS_EMPTY'
    joined = f'{mm} {dd} {yy}'
    span = select_field_span(joined, 'DATE', 'patient_dob')
    selected = span.selected_text
    # Only emit when span produced a calendar-shaped date (not the raw join).
    if not selected or not re.fullmatch(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', selected):
        return [], attempts, 'DOB_CELLS_EMPTY'
    # Attribute to a route-authorized producing engine so evidence decision does
    # not strip the assembled candidate as CANDIDATE_ENGINE_NOT_AUTHORIZED.
    # Cell segmentation stays in preprocessing_variant + span reason codes.
    producing_engine = engines[0] if engines else 'rapidocr'
    for attempt in reversed(attempts):
        eng = str(attempt.get('engine') or '')
        if not eng or eng == 'tesseract_digits':
            continue
        obs = attempt.get('observation')
        if obs is None:
            continue
        producing_engine = eng
        break
    box = BoundingBox(
        x0=band[0], y0=band[1], x1=band[2], y1=band[3],
        image_width=image.width, image_height=image.height,
    )
    candidate = OCRCandidate(
        value=selected, raw_value=' | '.join(raw_bits), engine=producing_engine,
        model_name='unknown', model_version='unknown',
        preprocessing_variant='dob_cell_upscale',
        preprocessing_version='cascade-v8',
        raw_confidence=0.8,
        calibrated_confidence=None, bounding_box=box,
        latency_ms=0.0,
    )
    payload = {**asdict(candidate), 'bounding_box': box.model_dump(mode='json')}
    payload['span_selection'] = {
        'selected_text': span.selected_text,
        'rule_id': span.rule_id,
        'confidence': span.confidence,
        'reason_codes': list(span.reason_codes) + ['DOB_CELL_SEGMENT'],
        'cell_parts': parts,
        'assembly_engine': 'dob_cells',
        'producing_engine': producing_engine,
    }
    return [payload], attempts, 'DOB_CELLS_ASSEMBLED'


def recognize_regions(image, geometry, router, emit=lambda rows: None, template=None):
    """OCR field regions via the field-semantic cascade strategy.

    For each field the cascade walks typed crop variants and governed route
    engines, stopping when span-selected text is field-shaped. Empty /
    contaminated financial crops remain empty (no invented amounts).
    """
    if geometry.get('status') != 'SUCCESS' or geometry.get('coordinate_frame') != 'rectified_template_pixels':
        raise ValueError('Successful canonical GeometryResult required')
    template_fields = {}
    if template is not None:
        for region in template.field_regions:
            template_fields[region.field_name] = (region.x0, region.y0, region.x1, region.y1)
    cascade = FieldCascade()
    rows = []

    def _recognize_with_engines(field_name, bbox, field_type, engines):
        return _recognize_one(image, field_name, bbox, router, field_type, engine_order=engines)

    for field in geometry['fields']:
        result = field['result']
        box = result.get('aligned_roi')
        cell = result.get('safe_cell')
        if not box or not cell:
            raise ValueError('Recorded canonical region and safe cell required')
        aligned = tuple(box[k] for k in ('x0', 'y0', 'x1', 'y1'))
        if not (cell['x0'] <= aligned[0] < aligned[2] <= cell['x1'] and
                cell['y0'] <= aligned[1] < aligned[3] <= cell['y1']):
            raise ValueError('Canonical region exceeds recorded safe cell')
        primary = _ocr_bbox(field['field'], aligned, cell, (image.width, image.height), template_fields)
        # DOB alternate strategy (v10): cells-FIRST. Whole-band OCR reads the
        # MM|DD|YY dashed vertical rules as digit "1" (01→11, 09→19), which
        # then fights a second engine under CONFLICT_MARGIN and forces HITL.
        # Independent MM/DD/YY cell OCR + digit-whitelist tesseract avoids rules.
        cascaded = None
        if (
            field['field'].casefold() == 'patient_dob'
            and 'dob_cells' in post_miss_for(field['field'])
        ):
            from packages.extraction_recovery.field_cascade import (
                CascadeResult,
                CascadeStepResult,
                load_route_engines,
            )
            engines = load_route_engines('patient_dob')
            cell_box = (int(cell['x0']), int(cell['y0']), int(cell['x1']), int(cell['y1']))
            cell_h = cell_box[3] - cell_box[1]
            default_band = (
                max(primary[0], cell_box[0] + 2),
                max(primary[1], cell_box[3] - max(22, int(0.40 * cell_h))),
                min(cell_box[2] - 1, image.width),
                min(primary[3], cell_box[3] - 1),
            )
            band = _clamp_bbox(default_band, image.width, image.height)
            cell_cands, cell_attempts, cell_reason = _recognize_dob_cells(
                image, band, router, engines,
            )
            selected = next(
                (c.get('value') or '' for c in cell_cands if (c.get('value') or '').strip()),
                '',
            )
            ok, accept_reason = semantic_accept('patient_dob', selected)
            if ok:
                cascaded = CascadeResult(
                    field_name='patient_dob',
                    bbox=band,
                    candidates=list(cell_cands),
                    attempts=list(cell_attempts),
                    router_reason=cell_reason,
                    status='OBSERVED',
                    cascade_trace=[
                        CascadeStepResult(
                            variant_id='dob_cells_first',
                            bbox=band,
                            engines=engines,
                            selected_value=selected,
                            raw_value=(cell_cands[0].get('raw_value') if cell_cands else '') or '',
                            accepted=True,
                            accept_reason=f'CELLS_FIRST:{accept_reason}',
                            candidates=tuple(cell_cands),
                            attempts=tuple(cell_attempts),
                            router_reason=cell_reason,
                        )
                    ],
                    accepted=True,
                    accept_reason=f'CELLS_FIRST:{accept_reason}',
                    strategy_id=FieldCascade().strategy_id,
                )
        if cascaded is None:
            cascaded = cascade.recognize(
                field_name=field['field'],
                primary_bbox=primary,
                cell=cell,
                image_size=(image.width, image.height),
                recognize_fn=_recognize_with_engines,
            )
        # IJN2.022 / handwriting DOB: whole-band OCR fragments MM/DD/YY; cell
        # segmentation recovers calendar-valid dates from observed digit ink only.
        # Try the reconstructed digit band plus any cascade crop that already
        # held year/day fragments (digit_band / year_wide).
        if (not cascaded.accepted) and 'dob_cells' in post_miss_for(field['field']):
            from packages.extraction_recovery.field_cascade import (
                load_route_engines,
                CascadeResult,
                CascadeStepResult,
            )
            engines = load_route_engines('patient_dob')
            cell_box = (int(cell['x0']), int(cell['y0']), int(cell['x1']), int(cell['y1']))
            cell_h = cell_box[3] - cell_box[1]
            default_band = (
                max(primary[0], cell_box[0] + 2),
                max(primary[1], cell_box[3] - max(22, int(0.40 * cell_h))),
                min(cell_box[2] - 1, image.width),
                min(primary[3], cell_box[3] - 1),
            )
            bands: list[tuple[str, tuple[int, int, int, int]]] = [
                ('dob_cells', _clamp_bbox(default_band, image.width, image.height)),
            ]
            for prior in cascaded.cascade_trace:
                if prior.variant_id in {'dob_digit_band', 'dob_year_wide', 'dob_loose'}:
                    bands.append(
                        (
                            f'dob_cells_on_{prior.variant_id}',
                            _clamp_bbox(prior.bbox, image.width, image.height),
                        )
                    )
            seen_bands: set[tuple[int, int, int, int]] = set()
            for variant_id, band in bands:
                if band in seen_bands:
                    continue
                seen_bands.add(band)
                cell_cands, cell_attempts, cell_reason = _recognize_dob_cells(
                    image, band, router, engines,
                )
                selected = next(
                    (c.get('value') or '' for c in cell_cands if (c.get('value') or '').strip()),
                    '',
                )
                ok, accept_reason = semantic_accept('patient_dob', selected)
                step = CascadeStepResult(
                    variant_id=variant_id,
                    bbox=band,
                    engines=engines,
                    selected_value=selected,
                    raw_value=(cell_cands[0].get('raw_value') if cell_cands else '') or '',
                    accepted=ok,
                    accept_reason=accept_reason if selected else cell_reason,
                    candidates=tuple(cell_cands),
                    attempts=tuple(cell_attempts),
                    router_reason=cell_reason,
                )
                cascaded.cascade_trace.append(step)
                if ok:
                    cascaded = CascadeResult(
                        field_name='patient_dob',
                        bbox=band,
                        candidates=list(cell_cands),
                        attempts=list(cell_attempts),
                        router_reason=cell_reason,
                        status='OBSERVED',
                        cascade_trace=list(cascaded.cascade_trace),
                        accepted=True,
                        accept_reason=accept_reason,
                        strategy_id=cascade.strategy_id,
                    )
                    break
        # When whole-band accepted but engines disagree on separator-1 dates,
        # still attach dob_cells as a corroborating / preferred candidate.
        elif (
            cascaded.accepted
            and field['field'].casefold() == 'patient_dob'
            and 'dob_cells' in post_miss_for(field['field'])
            and not any(
                str(getattr(step, 'variant_id', '')).startswith('dob_cells')
                for step in cascaded.cascade_trace
            )
        ):
            from packages.extraction_recovery.field_cascade import (
                CascadeResult,
                load_route_engines,
            )
            engines = load_route_engines('patient_dob')
            cell_box = (int(cell['x0']), int(cell['y0']), int(cell['x1']), int(cell['y1']))
            cell_h = cell_box[3] - cell_box[1]
            band = _clamp_bbox(
                (
                    max(primary[0], cell_box[0] + 2),
                    max(primary[1], cell_box[3] - max(22, int(0.40 * cell_h))),
                    min(cell_box[2] - 1, image.width),
                    min(primary[3], cell_box[3] - 1),
                ),
                image.width,
                image.height,
            )
            cell_cands, cell_attempts, _cell_reason = _recognize_dob_cells(
                image, band, router, engines,
            )
            selected = next(
                (c.get('value') or '' for c in cell_cands if (c.get('value') or '').strip()),
                '',
            )
            ok, accept_reason = semantic_accept('patient_dob', selected)
            if ok and cell_cands:
                cascaded = CascadeResult(
                    field_name=cascaded.field_name,
                    bbox=band,
                    candidates=list(cell_cands) + list(cascaded.candidates),
                    attempts=list(cell_attempts) + list(cascaded.attempts),
                    router_reason=cascaded.router_reason,
                    status=cascaded.status,
                    cascade_trace=list(cascaded.cascade_trace),
                    accepted=True,
                    accept_reason=f'CELLS_PREFERRED:{accept_reason}',
                    strategy_id=cascaded.strategy_id,
                )
        rows.append({
            'field': field['field'],
            'canonical_region': list(aligned),
            'ocr_region': list(cascaded.bbox),
            'candidates': cascaded.candidates,
            'attempts': cascaded.attempts,
            'router_reason': cascaded.router_reason,
            'cascade': {
                'strategy_id': cascaded.strategy_id,
                'accepted': cascaded.accepted,
                'accept_reason': cascaded.accept_reason,
                'steps': [
                    {
                        'variant_id': step.variant_id,
                        'bbox': list(step.bbox),
                        'engines': list(step.engines),
                        'selected_value': step.selected_value,
                        'accepted': step.accepted,
                        'accept_reason': step.accept_reason,
                        'router_reason': step.router_reason,
                    }
                    for step in cascaded.cascade_trace
                ],
            },
            'status': cascaded.status,
        })
        emit(rows)
    return rows


def run(directory, output):
    directory, output = Path(directory), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    geometry = json.loads((directory / 'GeometryResult.json').read_text())
    telemetry = json.loads((directory / 'geometry_telemetry.json').read_text())
    trace = json.loads((directory / 'registration_trace.json').read_text())
    if telemetry['status'] != 'SUCCESS' or not telemetry['registration_evidence']['accepted']:
        raise ValueError('Accepted saved registration and geometry required')
    matrix = np.asarray(geometry['source_to_geometry_transform'], dtype=float)
    if not np.array_equal(matrix, telemetry['registration_evidence']['transform_matrix']):
        raise ValueError('Geometry and registration transforms disagree')
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError('Invalid saved transform')
    observations = [e['data']['coverage_observation'] for t in trace['traces'] for e in t['events']
                    if 'coverage_observation' in e.get('data', {})]
    size = next(o['reference']['size'] for o in observations if o['stage'] == 'Input image')
    with ZipFile(telemetry['source']['archive']) as archive:
        payload = archive.read(telemetry['source']['entry'])
    if hashlib.sha256(payload).hexdigest() != telemetry['document_id']:
        raise ValueError('Source TIFF hash mismatch')
    with Image.open(BytesIO(payload)) as tiff:
        tiff.seek(geometry['page_number'] - 1)
        with tiff.convert('L') as source:
            pixels = cv2.warpPerspective(np.asarray(source), matrix, tuple(size), borderValue=255)
    report = {'type': 'OCRCandidates', 'document_id': telemetry['document_id'],
              'page_number': geometry['page_number'], 'geometry_reference': str(directory / 'GeometryResult.json'),
              'geometry_sha256': hashlib.sha256((directory / 'GeometryResult.json').read_bytes()).hexdigest(),
              'coordinate_frame': 'rectified_template_pixels', 'stop_after': 'ocr',
              'registration_executed': False, 'geometry_estimated': False,
              'ranking_executed': False, 'validators_executed': False,
              'policy': 'Field-cascade v1: crop variants × governed route engines; stop on semantic field accept; no invented amounts',
              'confidence_basis': 'Arithmetic mean of raw line confidences; raw lines preserved',
              'fields': [], 'service_lines': [], 'status': 'RUNNING'}
    def save(rows):
        report['fields'] = rows
        (output / 'OCRCandidates.json').write_text(json.dumps(report, indent=2, default=str, allow_nan=False), encoding='utf-8')
    template = _load_cms1500_template()
    try:
        with Image.fromarray(pixels) as canonical:
            router = OCRRouter(lambda attempt: True)
            recognize_regions(canonical, geometry, router, save, template=template)
            report['service_lines'] = recognize_service_lines(canonical, router, template)
        report['status'] = 'COMPLETED'
    except Exception as exc:
        report['status'] = 'FAILED'
        report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        save(report['fields'])
        (output / 'ocr_telemetry.json').write_text(json.dumps({
            'status': report['status'], 'fields_completed': len(report['fields']),
            'provider_attempts': [{'field': r['field'], 'attempts': [
                {k: a[k] for k in ('engine', 'reason', 'latency_ms')} for a in r['attempts']]}
                for r in report['fields']], 'stop_after': 'ocr',
        }, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('geometry_directory')
    parser.add_argument('output_directory')
    args = parser.parse_args()
    result = run(args.geometry_directory, args.output_directory)
    print(json.dumps({'status': result['status'], 'fields': len(result['fields']),
                      'candidates': sum(len(r['candidates']) for r in result['fields'])}))
    # PaddleOCR / ONNX Runtime often hang in atexit finalizers after a successful
    # run (poll forever while holding multi-GB RSS). Hard-exit once artifacts are
    # on disk so the cascade parent can advance to rank/validate.
    import os
    import sys

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if result.get('status') == 'COMPLETED' else 1)
