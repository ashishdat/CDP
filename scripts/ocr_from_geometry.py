"""Resume saved canonical geometry through OCR candidates only.

Run: python -m scripts.ocr_from_geometry GEOMETRY_DIRECTORY OUTPUT_DIRECTORY
"""
import argparse
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
    # Phase 2: apply field-typed preprocess on the crop, then OCR the enhanced crop.
    x0, y0, x1, y1 = (int(v) for v in bbox)
    crop = image.crop((x0, y0, x1, y1))
    applied = _preprocessing_registry().apply(crop, name, field_type or '')
    crop_image = applied.image
    crop_bbox = (0, 0, crop_image.width, crop_image.height)
    routed = router.route(OCRRouteRequest(crop_image, crop_bbox, engine_order=engine_order))
    candidates = []
    attempts = []
    for attempt in routed.attempts:
        observation = attempt.observation
        attempts.append({'engine': attempt.engine, 'reason': attempt.reason,
                         'latency_ms': attempt.latency_ns / 1e6,
                         'observation': asdict(observation) if observation else None,
                         'preprocessing_profile': applied.profile})
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
            preprocessing_variant=applied.profile,
            preprocessing_version=applied.version,
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
                import re as _re_noise
                if _re_noise.search(r'[^0-9A-Z.\s,-]', (raw or '').upper()) or _re_noise.fullmatch(r'[\s\-.,]*', raw or ''):
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
        cascaded = cascade.recognize(
            field_name=field['field'],
            primary_bbox=primary,
            cell=cell,
            image_size=(image.width, image.height),
            recognize_fn=_recognize_with_engines,
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
