"""Consistent ledger-snapshot reporting; observational, never acceptance authority."""
from pathlib import Path
import json, hashlib, statistics
from collections import Counter
from datetime import datetime, timezone

def digest(data):
    return hashlib.sha256(data).hexdigest()

def snapshot(ledger, selected):
    payload = Path(ledger).read_bytes() if Path(ledger).exists() else b''
    committed = payload[:payload.rfind(b'\n') + 1]
    latest, extras, errors = {}, set(), []
    for index, line in enumerate(committed.splitlines()):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            errors.append({'line':index+1, 'issue':'MALFORMED_COMMITTED_ROW'})
            continue
        document = row.get('document')
        if document not in selected:
            extras.add(str(document))
            continue
        latest[document] = row
    return list(latest.values()), {'committed_sha256':digest(committed), 'committed_bytes':len(committed),
        'ignored_partial_bytes':len(payload)-len(committed), 'unselected_documents':sorted(extras), 'errors':errors}

def outcomes(rows, selected_count):
    counts = Counter()
    issues = []
    for row in rows:
        if not row.get('finished'):
            continue
        disp = row.get('disposition')
        if row.get('true_stp') and disp != 'TRUE_STP':
            issues.append({'claim':row.get('claim_id'), 'issue':'STP_FLAG_DISPOSITION_MISMATCH'})
        if disp == 'TRUE_STP' and row.get('completed') and row.get('true_stp'):
            counts['stp'] += 1
        elif disp == 'HITL' and row.get('completed'):
            counts['hitl'] += 1
        elif disp == 'NOT_A_CLAIM_DOCUMENT' or (disp == 'REGISTRATION_FAILED' and (row.get('unstructured_reg_fallback') or {}).get('reason') == 'MAILROOM_OR_FAX'):
            counts['non_claim'] += 1
        elif not row.get('completed'):
            counts['terminal_failure'] += 1
        else:
            counts['other_completed'] += 1
            issues.append({'claim':row.get('claim_id'), 'issue':'UNRECOGNIZED_COMPLETED_DISPOSITION'})
    finished = sum(counts.values())
    completed = counts['stp'] + counts['hitl'] + counts['other_completed']
    if finished > selected_count:
        raise ValueError('Finished count exceeds selected sample')
    result = {k:counts[k] for k in ('stp','hitl','non_claim','terminal_failure','other_completed')}
    result.update(selected=selected_count, finished=finished, completed=completed, pending=selected_count-finished)
    eligible_claim_inputs=selected_count-counts['non_claim']
    result['eligible_claim_inputs']=eligible_claim_inputs
    result['valid_non_claim_rejections']=counts['non_claim']
    result['rates'] = {'stp_of_all_selected':counts['stp']/selected_count,
        'stp_of_claim_inputs':counts['stp']/eligible_claim_inputs if eligible_claim_inputs else None,
        'stp_of_finished':counts['stp']/finished if finished else None,
        'stp_of_completed':counts['stp']/completed if completed else None,
        'hitl_of_finished':counts['hitl']/finished if finished else None,
        'final_stp_lower_bound':counts['stp']/selected_count,
        'final_stp_upper_bound':(counts['stp']+selected_count-finished)/selected_count,
        'final_rate_available':finished == selected_count}
    return result, issues

def field_diagnosis(claim, row):
    from packages.extraction_recovery.dob_confirmation import dob_component_conflicts, dob_reads_confirmed
    from packages.ocr.evidence_eligibility import eligible_candidates
    files = {'ocr':claim/'ocr/OCRCandidates.json', 'decision':claim/'final/DecisionResult.json'}
    artifacts, identities, issues = {}, {}, []
    for name, path in files.items():
        if not path.exists():
            identities[name] = {'status':'MISSING'}
            continue
        payload = path.read_bytes()
        try:
            artifacts[name] = json.loads(payload)
            identities[name] = {'status':'AVAILABLE','path':str(path),'sha256':digest(payload)}
        except ValueError:
            identities[name] = {'status':'MALFORMED','sha256':digest(payload)}
    ocr_fields = {f['field']:f for f in artifacts.get('ocr',{}).get('fields',[]) if f.get('field')}
    decisions = {f['field_name']:f for f in artifacts.get('decision',{}).get('field_decisions',[]) if f.get('field_name')}
    diagnoses = []
    for name in row.get('critical_blockers') or []:
        state = (row.get('fields') or {}).get(name) or {}
        decision = decisions.get(name)
        reasons = state.get('reasons') or []
        if decision is not None and set(reasons) != set(decision.get('reason_codes') or []):
            issues.append({'claim':row.get('claim_id'),'field':name,'issue':'LEDGER_DECISION_REASON_MISMATCH'})
        f = ocr_fields.get(name)
        diagnosis = {'field':name,'ledger_reasons':reasons,'decision_reasons':decision.get('reason_codes') if decision else None,
                     'decision_artifact_available':decision is not None,'ocr_artifact_available':f is not None,
                     'physical_cause_status':'NOT_ESTABLISHED_BY_REASON_CODE'}
        if f and name in {'patient_dob','date_of_birth','dob'}:
            candidates, attempts = f.get('candidates') or [], f.get('attempts') or []
            observed = dob_component_conflicts(candidates, attempts)
            saved = f.get('dob_component_conflicts')
            diagnosis.update(saved_ocr_component_conflicts=saved, recomputed_component_conflicts=observed,
                independent_date_confirmation=dob_reads_confirmed(candidates, attempts),
                candidate_count=len(candidates), eligible_candidate_count=len(eligible_candidates(candidates)),
                component_attempt_count=sum(bool((a.get('observation') or {}).get('parts')) for a in attempts),
                diagnostic_basis='RECOMPUTED_FROM_FINAL_SAVED_CANDIDATES_AND_COMPONENT_ATTEMPTS')
            if saved is not None and saved != observed:
                issues.append({'claim':row.get('claim_id'),'field':name,'issue':'STALE_OCR_COMPONENT_CONFLICT_SUMMARY'})
            if 'DOB_COMPONENT_CONFLICT' in reasons and not observed:
                diagnosis['conflict_trace_status'] = 'FINAL_DECISION_CONFLICT_NOT_REPRODUCED_FROM_OCR_ARTIFACT'
                issues.append({'claim':row.get('claim_id'),'field':name,'issue':'DECISION_CONFLICT_TRACE_INCOMPLETE'})
            else:
                diagnosis['conflict_trace_status'] = 'REPRODUCED' if observed else 'NO_COMPONENT_CONFLICT'
        diagnoses.append(diagnosis)
    return {'claim':row.get('claim_id'),'artifacts':identities,'fields':diagnoses}, issues

def build(run, manifest=None, profile="PRODUCT"):
    from packages.recovery.independent_failures import failure_category
    run = Path(run).resolve()
    manifest = manifest if manifest is not None else json.loads((run/'benchmark_manifest.json').read_text())
    rows, sources, evidence, issues = [], [], [], []
    for entry in manifest['corpora']:
        root = run/profile.lower()/f"corpus_{entry['pool_size']}"
        current, provenance = snapshot(root/'results.jsonl', set(entry['documents']))
        sources.append({'corpus':entry['pool_size'], **provenance})
        rows.extend(current)
        for row in current:
            if not row.get('finished') or row.get('disposition') != 'HITL':
                continue
            claim = (root/'claims'/str(row.get('claim_id') or '')).resolve()
            if not claim.is_relative_to(root/'claims'):
                raise ValueError('Claim path escapes run')
            result, detected = field_diagnosis(claim, row)
            evidence.append(result)
            issues.extend(detected)
    count = sum(e['sample_size'] for e in manifest['corpora'])
    totals, detected = outcomes(rows, count)
    issues.extend(detected)
    finished = [r for r in rows if r.get('finished')]
    stages = Counter(failure_category(r) for r in finished)
    overlap = Counter(failure_category(r) for r in finished if r.get('completed') and r.get('disposition')=='HITL')
    elapsed = [r['elapsed_sec'] for r in finished if isinstance(r.get('elapsed_sec'), (int,float)) and r['elapsed_sec'] >= 0]
    return {'schema_version':'run-reporting-v321','status':'COMPLETE' if not totals['pending'] else 'RUNNING',
        'updated_at':datetime.now(timezone.utc).isoformat(),'terminal_outcomes':totals,
        'stage_categories':dict(stages),'stage_categories_with_completed_hitl':dict(overlap),
        'stage_counts_are_not_additional_terminal_failures':True,
        'blocker_claim_counts':dict(Counter(f for r in finished if r.get('disposition')=='HITL' for f in set(r.get('critical_blockers') or []))),
        'timing':{'finished_observations':len(elapsed),'mean_document_seconds':statistics.mean(elapsed) if elapsed else None,
                  'median_document_seconds':statistics.median(elapsed) if elapsed else None},
        'reporting_issue_counts':dict(Counter(i['issue'] for i in issues)),'reporting_issues':issues,
        'ledger_snapshots':sources,'hitl_evidence':evidence,
        'acceptance_rules_changed':False,'independent_accuracy_established':False,
        'snapshot_scope':'One committed byte snapshot per ledger; artifacts are separately hashed observations; producer reports may update later'}
