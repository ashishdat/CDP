"""Local DOB repair and canonical decision replay on the same failing samples."""
from __future__ import annotations

import hashlib
import argparse
import json
import os
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import cv2
    import numpy as np
    from PIL import Image

    from packages.extraction_recovery.span_selection import select_field_span
    from scripts import benchmark_hackathon_four_corpora as benchmark
    from scripts.assemble_extraction_result import assemble
    from scripts.complete_from_extraction import run as complete
    from scripts.ocr_from_geometry import _attach_local_dob_confirmation, _load_cms1500_template
    from scripts.ocr_from_geometry import _field_observation_text
    from types import SimpleNamespace
    from scripts.rank_from_ocr import rank_saved
    from scripts.run_hackathon_1000_cascade import _summarize_final
    from scripts.validate_from_ranked import run as validate

    source = ROOT / 'evaluation_results/benchmark_review_5x10_round3_fixed'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path, default=ROOT / 'evaluation_results/hitl_dob_recovery_verified')
    parser.add_argument('--local-handwriting', action='store_true')
    args = parser.parse_args()
    output = args.output_root.resolve()
    if output.exists():
        raise ValueError('Use a fresh verification directory')
    output.mkdir()
    benchmark.OUT = output
    manifest = json.loads((source / 'benchmark_manifest.json').read_text())
    entry = next(e for e in manifest['corpora'] if e['pool_size'] == 100)
    env = benchmark.run_env(output, entry['sample_archive'], 'LOCAL_ONLY')
    os.environ.clear()
    os.environ.update(env)
    if args.local_handwriting:
        import torch

        from workers.ocr_engine_factories import wire_package_ocr_providers

        torch.set_num_threads(1)
        wire_package_ocr_providers()
    before = {}
    for line in (source / 'local_only/corpus_100/results.jsonl').read_text().splitlines():
        row = json.loads(line)
        before[row['claim_id']] = row
    records = []
    with ZipFile(entry['sample_archive']) as archive:
        for document in entry['documents']:
            cid = document.replace('/', '__')
            old = source / 'local_only/corpus_100/claims' / cid
            target = output / 'claims' / cid
            target.mkdir(parents=True)
            gp = next(old.rglob('GeometryResult.json'))
            geometry = json.loads(gp.read_text())
            telemetry = json.loads((gp.parent / 'geometry_telemetry.json').read_text())
            template = _load_cms1500_template(geometry, telemetry, gp.parent)
            payload = archive.read(document)
            if hashlib.sha256(payload).hexdigest() != telemetry['document_id']:
                raise ValueError('Source bytes changed')
            with Image.open(BytesIO(payload)) as image:
                image.seek(geometry['page_number'] - 1)
                pixels = cv2.warpPerspective(np.asarray(image.convert('L')),
                                            np.asarray(geometry['source_to_geometry_transform']),
                                            (template.reference_dimensions.width_px,
                                             template.reference_dimensions.height_px), borderValue=255)
            old_ocr = old / 'ocr/OCRCandidates.json'
            report = json.loads(old_ocr.read_text())
            index = next(i for i, f in enumerate(report['fields']) if f['field'] == 'patient_dob')
            field = report['fields'][index]
            for candidate in field['candidates']:
                raw = candidate.get('raw_value') or ''
                for attempt in field['attempts']:
                    lines = (attempt.get('observation') or {}).get('lines') or []
                    if (attempt.get('engine') == candidate.get('engine') and lines
                            and '\n'.join(line['text'] for line in lines) == raw):
                        if all('x0' in line and 'y0' in line for line in lines):
                            raw = _field_observation_text(SimpleNamespace(
                                lines=[SimpleNamespace(**line) for line in lines]), 'patient_dob')
                        break
                span = select_field_span(raw, 'DATE', 'patient_dob')
                if span.selected_text and (span.rule_id == 'span-v2-date-compact-observed'
                                          or raw != candidate.get('raw_value')):
                    candidate['raw_value'] = raw
                    candidate['value'] = span.selected_text
                    candidate['span_selection'] = span.model_dump(mode='json')
            region = next(r for r in template.field_regions if r.field_name == 'patient_dob')
            with Image.fromarray(pixels) as canonical:
                report['fields'][index] = _attach_local_dob_confirmation(
                    field, canonical, (region.x0, region.y0, region.x1, region.y1))
                if args.local_handwriting:
                    from packages.extraction_recovery.dob_confirmation import dob_reads_confirmed
                    from packages.extraction_recovery.dob_trocr_residual import maybe_attach_dob_trocr_to_field_row

                    if not dob_reads_confirmed(report['fields'][index]['candidates']):
                        report['fields'][index] = maybe_attach_dob_trocr_to_field_row(
                            report['fields'][index], image=canonical, gap_class='AMBIGUOUS_DIGIT_FRAGMENTS')
            op = target / 'ocr/OCRCandidates.json'
            op.parent.mkdir()
            op.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
            stage_telemetry = json.loads((old / 'ocr/ocr_telemetry.json').read_text())
            stage_telemetry['local_dob_recovery'] = {
                'original_ocr_sha256': hashlib.sha256(old_ocr.read_bytes()).hexdigest(),
                'additional_attempts': report['fields'][index]['attempts'], 'cloud_calls': 0}
            (op.parent / 'ocr_telemetry.json').write_text(
                json.dumps(stage_telemetry, indent=2) + '\n', encoding='utf-8')
            rank_saved(op, target / 'rank')
            validate(target / 'rank/RankedCandidates.json', target / 'validate',
                     template.template_id, template.version)
            assemble(op, target / 'rank/RankedCandidates.json',
                     target / 'validate/ValidationResults.json', target / 'extract')
            complete(target / 'extract/ExtractionResult.json', target / 'final', 'CMS1500')
            current = _summarize_final(target)
            decision = json.loads((target / 'final/DecisionResult.json').read_text())
            dob = next(f for f in decision['field_decisions'] if f['field_name'] == 'patient_dob')
            record = {'claim_id': cid, 'before_stp': before[cid]['true_stp'],
                      'after_stp': current['true_stp'], 'dob_disposition': dob['disposition'],
                      'dob_reasons': dob['reason_codes'], 'remaining_blockers': current['critical_blockers']}
            records.append(record)
            print(json.dumps(record), flush=True)
    summary = {'scope': 'Same ten registered images; additional local DOB observations and canonical pipeline replay',
               'cloud_calls': 0, 'source_artifacts_unchanged': True,
               'before_stp': sum(r['before_stp'] for r in records),
               'after_stp': sum(r['after_stp'] for r in records), 'sample_size': len(records),
               'dob_accepted': sum(r['dob_disposition'] == 'AUTO_ACCEPTED' for r in records),
               'records': records, 'independent_accuracy_established': False}
    (output / 'verification_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'records'}), flush=True)


if __name__ == '__main__':
    main()
