"""Reevaluate historical DOB observations locally without trusting saved E2 flags."""
from __future__ import annotations

import hashlib
import inspect
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from packages.criticality import CriticalityLevel
    from packages.domain.common import BoundingBox
    from packages.evidence.models import StructuralLocalizationEvidence
    from packages.evidence.normalization import normalize_agreement_value
    from packages.evidence_decision import DecisionContext
    from packages.ocr.contracts import OCRCandidate
    from packages.ocr.provenance import EvidenceProvenance
    from packages.runtime_profile.decision_factory import DecisionServiceFactory

    root = ROOT / 'evaluation_results/benchmark_4x50_product_20261004/product'
    services = DecisionServiceFactory.from_profile()
    service = services.evidence_decision
    counts, reasons, cases = Counter(), Counter(), []
    allowed = set(inspect.signature(OCRCandidate).parameters)
    for cohort in sorted(root.glob('corpus_*')):
        latest = {}
        for line in (cohort / 'results.jsonl').read_text().splitlines():
            row = json.loads(line)
            latest[row['claim_id']] = row
        for row in latest.values():
            if not row.get('true_stp'):
                continue
            claim = cohort / 'claims' / row['claim_id']
            ocr_path = claim / 'ocr/OCRCandidates.json'
            decision_path = claim / 'final/DecisionResult.json'
            ocr_bytes, decision_bytes = ocr_path.read_bytes(), decision_path.read_bytes()
            old = json.loads(decision_bytes)
            old_field = next(f for f in old['field_decisions'] if f['field_name'] == 'patient_dob')
            items = (old_field.get('evidence_bundle') or {}).get('evidence_items') or []
            observed = next(f for f in json.loads(ocr_bytes)['fields'] if f['field'] == 'patient_dob')
            candidates = []
            for payload in observed['candidates']:
                fields = {k: v for k, v in payload.items() if k in allowed}
                fields['bounding_box'] = BoundingBox.model_validate(fields['bounding_box'])
                if fields.get('provenance'):
                    fields['provenance'] = EvidenceProvenance.model_validate(fields['provenance'])
                candidates.append(OCRCandidate(**fields))
            e3 = next(i for i in items if i['evidence_class'] == 'E3')
            metadata = e3.get('metadata') or {}
            structure = StructuralLocalizationEvidence(
                evidence_type=e3['evidence_type'], confidence=e3['confidence'], confirmed=True,
                source=e3['source'], **{k: v for k, v in metadata.items()
                                       if k in StructuralLocalizationEvidence.model_fields
                                       and k not in {'evidence_type', 'confidence', 'confirmed', 'source'}})
            deterministic = {i['metadata']['fact'] for i in items
                             if i['evidence_class'] == 'E4' and (i.get('metadata') or {}).get('fact')}
            cross_field = {i['evidence_type'] for i in items if i['evidence_class'] == 'E6'}
            current = service.decide(DecisionContext(
                field_name='patient_dob', document_family=old.get('document_family') or 'CMS1500',
                criticality=CriticalityLevel(old_field.get('criticality') or 'C2'), candidates=candidates,
                deterministic_evidence=deterministic, hard_validation_passed=True,
                registration_confidence=old.get('registration_confidence'),
                structural_localization=structure, cross_field_evidence=cross_field))
            counts[current.disposition.value] += 1
            reasons.update(current.reason_codes)
            invalid_e2 = [i for i in items if i['evidence_class'] == 'E2'
                          and i.get('independent') and len(set((i.get('metadata') or {}).get('engines') or [])) == 1]
            counts['historical_single_reader_E2'] += bool(invalid_e2)
            counts['historical_single_reader_E2_without_E5_E6'] += bool(invalid_e2) and not any(
                i['evidence_class'] in {'E5', 'E6'} for i in items)
            cases.append({'claim_id': row['claim_id'], 'cohort': cohort.name,
                          'historical_field_disposition': old_field['disposition'],
                          'current_field_disposition': current.disposition.value,
                          'current_reason_codes': current.reason_codes,
                          'selected_text_changed': current.selected_value != old_field['selected_value'],
                          'normalized_calendar_changed': normalize_agreement_value('patient_dob', current.selected_value or '') != normalize_agreement_value('patient_dob', old_field['selected_value'] or ''),
                          'ocr_sha256': hashlib.sha256(ocr_bytes).hexdigest(),
                          'decision_sha256': hashlib.sha256(decision_bytes).hexdigest()})
            assert ocr_path.read_bytes() == ocr_bytes and decision_path.read_bytes() == decision_bytes
    report = {'scope': 'DOB field replay on the same 149 historical STP OCR observations; not a new end-to-end STP or accuracy measurement',
              'historical_stp_claims': len(cases), 'counts': dict(counts), 'reason_counts': dict(reasons),
              'cloud_calls': 0, 'source_artifacts_unchanged': True,
              'runtime_profile': services.profile.decision_identity(),
              'independent_accuracy_established': False, 'cases': cases}
    output = ROOT / 'evaluation_results/version_accuracy_audit_20261005/matched_dob_replay.json'
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'claims': len(cases), 'counts': dict(counts)}))


if __name__ == '__main__':
    main()
