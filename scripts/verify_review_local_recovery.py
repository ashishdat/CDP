"""Verify bounded local field recovery against saved accepted geometry."""
from __future__ import annotations

import json
import os
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import faulthandler

    faulthandler.dump_traceback_later(60, repeat=True)
    import cv2
    import numpy as np
    import torch  # Windows: load Torch before Paddle's native DLLs.
    from PIL import Image

    from packages.ocr_router import OCRRouter
    from packages.templates.registry import TemplateRegistry
    from scripts import benchmark_hackathon_four_corpora as benchmark
    from scripts.ocr_from_geometry import _recognize_dob_cells, recognize_service_lines
    from workers.ocr_engine_factories import wire_package_ocr_providers

    _ = torch
    root = ROOT / 'evaluation_results/benchmark_review_5x10_20261005'
    manifest = json.loads((root / 'benchmark_manifest.json').read_text())
    entry = next(e for e in manifest['corpora'] if e['pool_size'] == 5000)
    benchmark.OUT = root
    env = benchmark.run_env(root / 'local_verification', entry['sample_archive'], 'LOCAL_ONLY')
    os.environ.clear()
    os.environ.update(env)
    # This helper already started before run_env supplied PYTHONPATH; apply the
    # same RapidOCR thread cap explicitly before constructing any reader.
    from importlib import import_module

    import_module('scripts.benchmark_runtime.sitecustomize')
    torch.set_num_threads(1)
    wire_package_ocr_providers()
    router = OCRRouter(lambda attempt: True)
    registry = TemplateRegistry.load_from_directory()
    from packages.domain.enums import ClaimFormType

    template = registry.get_for_release(ClaimFormType.CMS1500, ROOT / 'config/releases/extraction-v3.yaml')
    reference = registry.load_reference_image(template)
    claim = root / 'local_only/corpus_5000/claims/Group A__M0471JEV.035'
    geometry = json.loads(next(claim.rglob('GeometryResult.json')).read_text())
    old = json.loads((claim / 'ocr/OCRCandidates.json').read_text())
    with ZipFile(entry['sample_archive']) as archive, Image.open(
        BytesIO(archive.read('Group A/M0471JEV.035'))
    ) as source:
        source.seek(geometry['page_number'] - 1)
        pixels = cv2.warpPerspective(np.asarray(source.convert('L')),
                                    np.asarray(geometry['source_to_geometry_transform']),
                                    reference.size, borderValue=255)
    with Image.fromarray(pixels) as image:
        lines = recognize_service_lines(image, router, template)
        dob = next(f for f in old['fields'] if f['field'] == 'patient_dob')
        region = next(f for f in template.field_regions if f.field_name == 'patient_dob')
        band = (dob['ocr_region'][0],
                max(region.y0 + 1, region.y1 - max(32, int(0.60 * (region.y1 - region.y0)))),
                dob['ocr_region'][2], region.y1 - 1)
        candidates, attempts, reason = _recognize_dob_cells(
            image, band, router, ('rapidocr', 'paddleocr'))
    report = {'profile': 'LOCAL_ONLY', 'cloud_calls': 0,
              'claim_id': 'Group A__M0471JEV.035',
              'previous_observed_charge_rows': len(old['service_lines']),
              'observed_charge_rows': len(lines),
              'charge_rows': [{'line': line['line_number'], 'amount': line['charges']} for line in lines],
              'dob_engines': [c['engine'] for c in candidates],
              'dob_engine_attempts': len(attempts), 'dob_status': reason,
              'dob_readers_agree': len(candidates) > 1 and len({c['value'] for c in candidates}) == 1,
              'acceptance_policy_changed': False}
    (root / 'local_recovery_verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
