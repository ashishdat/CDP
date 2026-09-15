"""Complete one saved ExtractionResult using existing decision policies only."""
import argparse
import json
from hashlib import sha256
from pathlib import Path
from time import perf_counter


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def _load_registration_context(extraction):
    """Load sibling registration/geometry artifacts for E3 without re-acquiring evidence."""
    from packages.evidence.models import (
        StructuralLocalizationEvidence,
        StructuralLocalizationType,
    )
    from packages.recovery.registration_recovery import evidence_grade_alignment_confidence

    artifacts = extraction.get('source_artifacts') or {}
    geometry_ref = artifacts.get('geometry') or {}
    geometry_path = Path(geometry_ref['path']) if geometry_ref.get('path') else None
    registration_confidence = None
    localizations = {}
    warnings = []

    document = None
    if geometry_path and geometry_path.is_file():
        document_path = geometry_path.parent / 'document.json'
        if document_path.is_file():
            document = json.loads(document_path.read_text(encoding='utf-8'))
        geometry = json.loads(geometry_path.read_text(encoding='utf-8'))
    else:
        geometry = None
        warnings.append({'reason': 'Geometry artifact unavailable; E3 structural localization omitted.'})

    if document:
        registration = document.get('registration') or {}
        evidence = registration.get('evidence') or {}
        accepted = registration.get('accepted') is True
        raw = registration.get('evidence_grade_alignment_confidence')
        if raw is None:
            raw = evidence.get('alignment_confidence')
        if raw is not None:
            registration_confidence = evidence_grade_alignment_confidence(
                float(raw), accepted=accepted,
            )
        elif accepted:
            # Accepted registration without a recorded score still clears the
            # low-confidence gate once remapped from the acceptance floor.
            registration_confidence = evidence_grade_alignment_confidence(0.40, accepted=True)

    if geometry and geometry.get('status') == 'SUCCESS' and registration_confidence is not None:
        confidence = float(registration_confidence)
        for row in geometry.get('fields') or []:
            name = row.get('field')
            result = row.get('result') or {}
            box = result.get('aligned_roi') or result.get('safe_cell')
            if not name or not isinstance(box, dict):
                continue
            try:
                bbox = (float(box['x0']), float(box['y0']), float(box['x1']), float(box['y1']))
            except (KeyError, TypeError, ValueError):
                continue
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                continue
            localizations[name] = StructuralLocalizationEvidence(
                evidence_type=StructuralLocalizationType.TEMPLATE_REGISTRATION_CONFIRMED,
                confidence=confidence,
                confirmed=True,
                reason_codes=(
                    'ACCEPTED_REGISTRATION_RECTIFIED_FRAME',
                    'TEMPLATE_FIELD_ROI_BOUNDED',
                ),
                source='geometry',
                field_name=name,
                field_bbox=bbox,
                localization_mode='TEMPLATE_ROI',
                positive_bounded_roi=True,
                geometry_valid=True,
                registration_compatible=True,
            )
    return registration_confidence, localizations, warnings


def decide(extraction, family):
    from pydantic import TypeAdapter
    from packages.ocr.contracts import OCRCandidate
    from packages.runtime_profile.decision_factory import DecisionServiceFactory
    from packages.deterministic_evidence.service import DeterministicEvidenceService
    from packages.claim_evidence.builder import ClaimEvidenceBuilder
    from packages.evidence_decision.contracts import DecisionContext
    from packages.claim_decision.contracts import ClaimDecisionContext, ClaimDisposition
    from packages.criticality import CriticalityLevel

    if extraction.get('type') != 'ExtractionResult' or extraction.get('status') != 'ASSEMBLED':
        raise ValueError('An assembled ExtractionResult is required')
    if family not in ('CMS1500', 'UB04'):
        raise ValueError('Explicit supported document family required')
    fields = extraction['field_results']
    names = [f['field_name'] for f in fields]
    if len(names) != len(set(names)) or not fields:
        raise ValueError('Nonempty, unique field results required')
    for f in fields:
        winner = f['ranked_candidate']
        validation = f['validation']
        if winner is None:
            if f['ocr']['candidates'] or validation is not None or f['status'] != 'NO_VALUE':
                raise ValueError('Inconsistent missing candidate')
        elif (validation is None or winner['field_id'] != f['field_name']
              or validation['candidate_id'] != winner['candidate_id']
              or validation['field_id'] != f['field_name']
              or validation['normalized_value'] != f['normalized_value']
              or validation['status'] != f['status']):
            raise ValueError('Extraction winner/validation lineage mismatch')
    services = DecisionServiceFactory.from_profile()
    deterministic = DeterministicEvidenceService()
    claim_id = extraction['document']['document_id']
    values = {f['field_name']: f['normalized_value'] for f in fields}
    # Existing cross-field facts feed the existing decision rules. No evidence acquisition.
    service_lines = extraction.get('service_lines') or []
    facts = ClaimEvidenceBuilder.load().build(claim_id=claim_id, document_family=family,
                                            claim_values=values, service_lines=service_lines)
    registration_confidence, localizations, structural_warnings = _load_registration_context(extraction)
    decisions, checks, critical = [], {}, []
    for f in fields:
        name = f['field_name']
        policy = services.field_policy.for_field(family, name)
        if policy.criticality in (CriticalityLevel.C2, CriticalityLevel.C3):
            critical.append({'field_name': name, 'criticality': policy.criticality.value,
                             'extraction_status': f['status'], 'required': policy.required})
        winner = f['ranked_candidate']
        raw = winner['ocr_candidate']['raw_value'] if winner else ''
        check = deterministic.evaluate(name, f['normalized_value'] or raw, claim_values=values)
        checks[name] = check.model_dump(mode='json')
        candidates = []
        validations = {v['candidate_id']: v for v in f['candidate_validations']}
        for row in ([winner] if winner else []) + f['alternatives']:
            candidate = dict(row['ocr_candidate'])
            validation = validations[row['candidate_id']]
            if row['is_winner']:
                candidate['value'] = validation['normalized_value']
            candidate['validation_results'] = tuple(validation['reason'])
            candidates.append(TypeAdapter(OCRCandidate).validate_python(candidate))
        localization = localizations.get(name)
        decisions.append(services.evidence_decision.decide(DecisionContext(
            field_name=name, document_family=family, criticality=policy.criticality,
            required=policy.required, blocks_stp=policy.blocks_stp,
            requires_review_when_unresolved=policy.requires_review_when_unresolved,
            candidates=candidates, deterministic_evidence=check.evidence,
            deterministic_evidence_version=deterministic.policy_version,
            hard_validation_passed=check.passed,
            registration_confidence=registration_confidence,
            structural_evidence_source='geometry' if localization is not None else None,
            structural_localization=localization,
            cross_field_evidence=set(check.cross_field_evidence) | facts.evidence_types_for(name))))
    claim = services.claim_decision.decide(ClaimDecisionContext(
        claim_id=claim_id, document_family=family, field_decisions=decisions,
        claim_evidence=facts.evidence_items, contradictions=facts.contradictions,
        process_integrity_valid=not extraction.get('errors')))
    present = {services.field_policy.canonical_name(family, name)
               for name, value in values.items() if value is not None and str(value).strip()}
    missing_required = sorted(set(services.field_policy.required_fields(family)) - present)
    missing_observed = sorted(f['field_name'] for f in fields
                              if f['status']=='NO_VALUE' or f['normalized_value'] is None
                              or not str(f['normalized_value']).strip())
    return {'type':'DecisionResult', 'status':'SUCCESS', 'document':extraction['document'],
        'page':extraction['page'], 'document_family':family,
        'claim_status':claim.disposition.value,
        'review_required':claim.disposition in (ClaimDisposition.FIELD_REVIEW_REQUIRED,
                                               ClaimDisposition.CLAIM_REVIEW_REQUIRED),
        'missing_fields':missing_required, 'missing_observed_fields':missing_observed,
        'critical_fields':critical, 'critical_blockers':claim.critical_blockers,
        'warnings':extraction.get('warnings',[]) + structural_warnings + [
            {'reason':'Structural localization reused from accepted registration/geometry; service-line charge OCR reused from extraction artifacts when present; no new reference acquisition.'}],
        'decision_reason':claim.reason_codes, 'claim_decision':claim.model_dump(mode='json'),
        'field_decisions':[d.model_dump(mode='json') for d in decisions],
        'deterministic_checks':checks, 'claim_facts':facts.model_dump(mode='json'),
        'extracted_fields':fields,
        'registration_confidence':registration_confidence,
        'missing_fields_basis':'Required policy fields absent or blank; invalid nonempty values are not missing.',
        'telemetry':{'extraction':extraction['telemetry']}}


def evidence_from_decision(path):
    """Read the persisted decision; preserve its policy outcome and supporting facts."""
    from packages.claim_decision.contracts import ClaimDecision
    from packages.evidence_decision.contracts import FieldDecision
    from packages.claim_evidence.builder import ClaimEvidenceResult
    path = Path(path)
    payload = path.read_bytes()
    decision = json.loads(payload)
    if decision.get('type') != 'DecisionResult' or decision.get('status') != 'SUCCESS':
        raise ValueError('Successful saved DecisionResult required')
    claim = ClaimDecision.model_validate(decision['claim_decision'])
    if claim.claim_id != decision['document']['document_id'] or claim.disposition.value != decision['claim_status']:
        raise ValueError('Claim decision identity/status mismatch')
    fields = [FieldDecision.model_validate(f) for f in decision['field_decisions']]
    facts = ClaimEvidenceResult.model_validate(decision['claim_facts'])
    evidence = {'decision_reference':str(path), 'decision_sha256':sha256(payload).hexdigest(),
                'extraction_reference':decision['extraction_reference'],
                'claim_facts':facts.model_dump(mode='json'),
                'fields':[{'field_name':f.field_name,'supporting_evidence':[e.model_dump(mode='json') for e in f.supporting_evidence],
                           'conflicting_evidence':[e.model_dump(mode='json') for e in f.conflicting_evidence],
                           'evidence_bundle':f.evidence_bundle.model_dump(mode='json') if f.evidence_bundle else None}
                          for f in fields], 'deterministic_checks':decision['deterministic_checks']}
    return {'type':'FinalClaim', 'status':'COMPLETED', 'document':decision['document'],
            'page':decision['page'], 'claim_status':decision['claim_status'],
            'review_required':decision['review_required'], 'stp_eligible':claim.stp_eligible,
            'missing_fields':decision['missing_fields'], 'critical_fields':decision['critical_fields'],
            'warnings':decision['warnings'], 'decision_reason':decision['decision_reason'],
            'field_results':decision['extracted_fields'], 'decision':decision,
            'evidence':evidence}


def run(source, output, family):
    source, output = Path(source), Path(output)
    payload = source.read_bytes()
    extraction = json.loads(payload)
    output.mkdir(parents=True, exist_ok=False)
    telemetry = {'input_sha256':sha256(payload).hexdigest(), 'events':[],
                 'upstream_executed':False, 'retries':0}
    stage = 'decision'
    started = perf_counter()
    try:
        decision = decide(extraction, family)
        decision['extraction_reference'] = {'path':str(source),'sha256':sha256(payload).hexdigest()}
        write(output/'DecisionResult.json', decision)
        telemetry['events'].append({'stage':stage,'status':'SUCCESS','latency_ms':(perf_counter()-started)*1000})
        stage = 'evidence'
        started = perf_counter()
        final = evidence_from_decision(output/'DecisionResult.json')
        write(output/'FinalClaim.json', final)
        telemetry['events'].append({'stage':stage,'status':'SUCCESS','latency_ms':(perf_counter()-started)*1000})
        return final
    except Exception as exc:
        telemetry['events'].append({'stage':stage,'status':'FAILED','latency_ms':(perf_counter()-started)*1000,
                                    'error':{'type':type(exc).__name__,'reason':str(exc)}})
        raise
    finally:
        telemetry['input_unchanged'] = source.read_bytes()==payload
        write(output/'completion_telemetry.json',telemetry)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('extraction_result')
    parser.add_argument('output_directory')
    parser.add_argument('--document-family',required=True,choices=['CMS1500','UB04'])
    args=parser.parse_args()
    result=run(args.extraction_result,args.output_directory,args.document_family)
    print(json.dumps({k:result[k] for k in ('status','claim_status','review_required','missing_fields')}))
