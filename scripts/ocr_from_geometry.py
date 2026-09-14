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
from packages.ocr.contracts import OCRCandidate
from packages.ocr_router import OCRRouter, OCRRouteRequest


def recognize_regions(image, geometry, router, emit=lambda rows: None):
    if geometry.get('status') != 'SUCCESS' or geometry.get('coordinate_frame') != 'rectified_template_pixels':
        raise ValueError('Successful canonical GeometryResult required')
    requests = []
    for field in geometry['fields']:
        result = field['result']
        box = result.get('aligned_roi')
        cell = result.get('safe_cell')
        if not box or not cell:
            raise ValueError('Recorded canonical region and safe cell required')
        bbox = tuple(box[k] for k in ('x0', 'y0', 'x1', 'y1'))
        if not (cell['x0'] <= bbox[0] < bbox[2] <= cell['x1'] and
                cell['y0'] <= bbox[1] < bbox[3] <= cell['y1']):
            raise ValueError('Canonical region exceeds recorded safe cell')
        requests.append((field['field'], OCRRouteRequest(image, bbox)))
    rows = []
    for name, request in requests:
        routed = router.route(request)
        candidates = []
        attempts = []
        for attempt in routed.attempts:
            observation = attempt.observation
            attempts.append({'engine': attempt.engine, 'reason': attempt.reason,
                             'latency_ms': attempt.latency_ns / 1e6,
                             'observation': asdict(observation) if observation else None})
            if observation is None or not observation.lines:
                continue
            raw = '\n'.join(line.text for line in observation.lines)
            box = BoundingBox(x0=request.bbox[0], y0=request.bbox[1],
                              x1=request.bbox[2], y1=request.bbox[3],
                              image_width=image.width, image_height=image.height)
            candidate = OCRCandidate(
                value=raw, raw_value=raw, engine=attempt.engine,
                model_name='unknown', model_version='unknown',
                preprocessing_variant='recorded_canonical_region',
                raw_confidence=float(np.mean([line.confidence for line in observation.lines])),
                calibrated_confidence=None, bounding_box=box,
                latency_ms=attempt.latency_ns / 1e6)
            candidates.append({**asdict(candidate), 'bounding_box': box.model_dump(mode='json')})
        rows.append({'field': name, 'canonical_region': list(request.bbox),
                     'candidates': candidates, 'attempts': attempts,
                     'router_reason': routed.reason,
                     'status': 'OBSERVED' if candidates else 'NO_OBSERVATION'})
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
              'policy': 'Existing router order; stop escalation on first usable observation; no confidence threshold or ranking',
              'confidence_basis': 'Arithmetic mean of raw line confidences; raw lines preserved',
              'fields': [], 'status': 'RUNNING'}
    def save(rows):
        report['fields'] = rows
        (output / 'OCRCandidates.json').write_text(json.dumps(report, indent=2, default=str, allow_nan=False), encoding='utf-8')
    try:
        with Image.fromarray(pixels) as canonical:
            recognize_regions(canonical, geometry, OCRRouter(lambda attempt: True), save)
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
