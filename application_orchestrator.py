"""Single-owner, fail-stop execution of one claim using existing subsystems.

Run: python application_orchestrator.py --document 'Group A/M048DJJF.002'
"""
import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from zipfile import ZipFile

STAGES = ('classification', 'registration', 'geometry', 'ocr', 'ranking',
          'validators', 'decision', 'evidence')
STATUSES = {'SUCCESS', 'FAILED', 'SKIPPED', 'UNAVAILABLE'}


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False) + '\n', encoding='utf-8')


@dataclass
class ApplicationResult:
    status: str = 'SKIPPED'
    current_stage: str | None = None
    completed_stages: list = field(default_factory=list)
    failed_stage: str | None = None
    stages: dict = field(default_factory=lambda: dict.fromkeys(STAGES, 'SKIPPED'))
    telemetry: list = field(default_factory=list)
    outputs: dict = field(default_factory=dict)


class ApplicationStateMachine:
    """Only this loop advances execution. Instances execute once, without retries."""

    def __init__(self, handlers):
        if set(handlers) != set(STAGES):
            raise ValueError('Exactly one handler per application stage is required')
        self.handlers = dict(handlers)
        self.executed = False

    def run(self, context, output):
        if self.executed:
            raise RuntimeError('Application execution cannot be retried')
        self.executed = True
        result = ApplicationResult()
        output = Path(output)
        output.mkdir(parents=True, exist_ok=False)
        for stage in STAGES:
            result.current_stage = stage
            started = perf_counter()
            event = {'stage': stage, 'timestamp': datetime.now(timezone.utc).isoformat()}
            try:
                returned = self.handlers[stage](context)
                if not isinstance(returned, dict) or returned.get('status') not in STATUSES:
                    raise ValueError('Stage must return an explicit application status')
                # Validate before admitting a stage result or advancing.
                json.dumps(returned, allow_nan=False)
                status = returned['status']
                result.outputs[stage] = returned
                event['telemetry_reference'] = returned.get('telemetry_reference')
            except Exception as exc:
                status = 'UNAVAILABLE' if isinstance(exc, (ImportError, FileNotFoundError, NotImplementedError)) else 'FAILED'
                event['error'] = {'type': type(exc).__name__, 'reason': str(exc)}
            event.update(status=status, latency_ms=(perf_counter() - started) * 1000)
            result.telemetry.append(event)
            result.stages[stage] = status
            result.status = status
            if status == 'SUCCESS':
                result.completed_stages.append(stage)
            else:
                result.failed_stage = stage
            write(output / 'ApplicationResult.json', asdict(result))
            if status != 'SUCCESS':
                break
        return result


class ClaimStages:
    """Thin bindings. No method invokes another application stage."""

    def __init__(self, document, dataset, output):
        self.document, self.dataset, self.output = document, dataset, Path(output)
        self.images = []

    def close(self):
        for image in self.images:
            image.close()

    def classification(self, context):
        from PIL import Image
        from datasets.registry import DatasetManager
        from packages.domain.enums import ClaimFormType
        from packages.templates.registry import TemplateRegistry
        from workers.cascade.tesseract_adapter import TesseractTextExtractor
        from workers.page_detection.page_classification import classify_page, write_classification_report

        dataset = DatasetManager.load(self.dataset)
        if not dataset.verify()['verified']:
            raise ValueError('Dataset integrity verification failed')
        with ZipFile(dataset.root) as archive:
            entries = [e for e in archive.infolist() if e.filename == self.document and not e.is_dir()]
            if len(entries) != 1:
                raise ValueError('Select exactly one document')
            payload = archive.read(entries[0])
        context.update(document_id=sha256(payload).hexdigest(),
                       source={'archive': str(dataset.root), 'entry': self.document})
        with Image.open(BytesIO(payload)) as image:
            if image.format != 'TIFF':
                raise ValueError('TIFF required')
            for page in range(image.n_frames):
                image.seek(page)
                self.images.append(image.convert('RGB'))
        self.registry = TemplateRegistry.load_from_directory()
        templates = [t for family in ClaimFormType for t in self.registry.all_for_form_type(family)]
        extractor = TesseractTextExtractor(psm=11)
        self.lines = {page: extractor.extract(image) for page, image in enumerate(self.images, 1)}
        pages = [classify_page(image, self.lines[page], templates, page)
                 for page, image in enumerate(self.images, 1)]
        write_classification_report(pages, self.output)
        context['pages'] = [asdict(page) for page in pages]
        return {'status': 'SUCCESS', 'document_id': context['document_id'],
                'pages': context['pages'], 'telemetry_reference': str(self.output/'classification_trace.json')}

    def registration(self, context):
        from app import register_classified_document
        from workers.page_detection.template_selector import TemplateSelector
        from workers.page_detection.registration_telemetry import collect_traces, save_traces
        with collect_traces() as traces:
            try:
                selection = TemplateSelector(self.registry).select(self.images, text_lines=self.lines)
                context['selection'] = asdict(selection)
                if selection.template_id is None:
                    return {'status': 'UNAVAILABLE', 'reason': selection.reason,
                            'selection': context['selection']}
                registered = register_classified_document(self.images, None, self.registry, selection)
                context['registration'] = registered
                return {**registered, 'selection': context['selection'],
                        'telemetry_reference': str(self.output/'registration_trace.json')}
            finally:
                save_traces(traces, self.output)

    def geometry(self, context):
        from app import resolve_registered_geometry
        result = resolve_registered_geometry(self.images, context['registration'], self.registry)
        write(self.output/'GeometryResult.json', result)
        write(self.output/'geometry_telemetry.json', {
            'stage': 'geometry', 'status': result['status'],
            'registration_reference': 'registration_trace.json',
            'result_reference': 'GeometryResult.json', 'ocr_executed': False,
            'registration_evidence': context['registration']['evidence'],
            'source': context['source'], 'document_id': context['document_id']})
        return {'status': result['status'], 'result_reference': str(self.output/'GeometryResult.json'),
                'telemetry_reference': str(self.output/'geometry_telemetry.json')}

    def ocr(self, context):
        from scripts.ocr_from_geometry import run
        report = run(self.output, self.output/'ocr')
        return {'status': 'SUCCESS' if report['status'] == 'COMPLETED' else 'FAILED',
                'result_reference': str(self.output/'ocr/OCRCandidates.json'),
                'telemetry_reference': str(self.output/'ocr/ocr_telemetry.json')}

    def ranking(self, context):
        from scripts.rank_from_ocr import rank_saved
        report, _ = rank_saved(self.output/'ocr/OCRCandidates.json', self.output/'ranking')
        return {'status': report['status'], 'result_reference': str(self.output/'ranking/RankedCandidates.json'),
                'telemetry_reference': str(self.output/'ranking/ranking_telemetry.json')}

    def validators(self, context):
        from scripts.validate_from_ranked import run
        registration = context['registration']
        report = run(self.output/'ranking/RankedCandidates.json', self.output/'validators',
                     registration['template_id'], registration['template_version'])
        context['validation'] = report
        return {'status': 'SUCCESS' if report['status'] == 'COMPLETED' else 'FAILED',
                'result_reference': str(self.output/'validators/ValidationResults.json'),
                'telemetry_reference': str(self.output/'validators/validator_telemetry.json')}

    def decision(self, context):
        from packages.claim_decision.contracts import ClaimDecisionContext
        from packages.evidence_decision.contracts import DecisionContext
        from packages.runtime_profile.decision_factory import DecisionServiceFactory
        from pydantic import TypeAdapter
        from packages.ocr.contracts import OCRCandidate

        family = self.registry.get(context['registration']['template_id'],
                                   context['registration']['template_version']).form_type.value
        fields = json.loads((self.output/'ocr/OCRCandidates.json').read_text())['fields']
        services = DecisionServiceFactory.from_profile()
        policy = services.field_policy
        service = services.evidence_decision
        ranked = json.loads((self.output/'ranking/RankedCandidates.json').read_text())
        validations = {v['candidate_id']: v for v in context['validation']['results']}
        if set(validations) != {r['candidate_id'] for r in ranked['ranked_candidates']}:
            raise ValueError('Ranking and validation candidate identities differ')
        decisions = []
        for row in fields:
            field_policy = policy.for_field(family, row['field'])
            # Individual validator success is not proof of hard validation.
            # Preserve the service's conservative defaults for absent evidence.
            candidates = []
            for ranked_row in ranked['ranked_candidates']:
                if ranked_row['field_id'] != row['field']:
                    continue
                validation = validations[ranked_row['candidate_id']]
                candidate = dict(ranked_row['ocr_candidate'])
                if ranked_row['is_winner']:
                    candidate['value'] = validation['normalized_value']
                candidate['validation_results'] = tuple(validation['reason'])
                candidates.append(TypeAdapter(OCRCandidate).validate_python(candidate))
            inputs = DecisionContext(field_name=row['field'], document_family=family,
                criticality=field_policy.criticality, required=field_policy.required,
                blocks_stp=field_policy.blocks_stp,
                requires_review_when_unresolved=field_policy.requires_review_when_unresolved,
                candidates=candidates)
            decisions.append(service.decide(inputs))
        claim = services.claim_decision.decide(ClaimDecisionContext(
            claim_id=context['document_id'], document_family=family, field_decisions=decisions))
        context.update(family=family, field_decisions=decisions)
        report = {'status': 'SUCCESS', 'claim': claim.model_dump(mode='json'),
                  'fields': [d.model_dump(mode='json') for d in decisions],
                  'warnings': ['Hard validation and cross-field evidence are not established by candidate validation; no recovery actions executed.']}
        write(self.output/'DecisionResult.json', report)
        return {'status': 'SUCCESS', 'result_reference': str(self.output/'DecisionResult.json'),
                'disposition': claim.disposition.value}

    def evidence(self, context):
        from packages.claim_evidence.builder import ClaimEvidenceBuilder
        values = {d.field_name: d.selected_value for d in context['field_decisions']}
        result = ClaimEvidenceBuilder.load().build(claim_id=context['document_id'],
                     document_family=context['family'], claim_values=values)
        write(self.output/'EvidenceResult.json', result.model_dump(mode='json'))
        return {'status': 'SUCCESS', 'result_reference': str(self.output/'EvidenceResult.json')}


def run_claim(document, dataset='dataset.yaml', output_root='runs'):
    output = Path(output_root)/('orchestrated-' + uuid4().hex)
    stages = ClaimStages(document, dataset, output)
    machine = ApplicationStateMachine({name: getattr(stages, name) for name in STAGES})
    try:
        result = machine.run({}, output)
        return output, result
    finally:
        stages.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--document', required=True)
    parser.add_argument('--dataset', default='dataset.yaml')
    parser.add_argument('--output-root', default='runs')
    args = parser.parse_args()
    path, result = run_claim(args.document, args.dataset, args.output_root)
    print(json.dumps({'path': str(path), 'status': result.status, 'failed_stage': result.failed_stage}))
    raise SystemExit(0 if result.status == 'SUCCESS' else 1)
