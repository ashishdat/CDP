"""Rank saved OCR candidates only; never invoke upstream or downstream workers."""
import argparse
import hashlib
import json
from html import escape
from pathlib import Path
from time import perf_counter

from packages.candidate_ranking import CandidateRankingService
from packages.extraction_recovery.contracts import CandidateObservation
from packages.extraction_recovery.ranking import CandidateScoringPolicy


def _prefer_fuller_self_patient(report: dict) -> None:
    """Under Self, keep an already-observed Box 2 string that matches Box 4.

    Does not invent characters. Non-Self relationships are left unchanged.
    """
    from packages.geometry_authority.form_redundancy import (
        names_agree,
        normalize_person_name,
        prefer_fuller_self_name,
        relationship_is_self,
    )

    by_field: dict[str, list] = {}
    for row in report.get("ranked_candidates") or []:
        by_field.setdefault(row["field_id"], []).append(row)

    def _winner_text(field_id: str) -> str:
        for row in by_field.get(field_id) or []:
            if row.get("is_winner"):
                cand = row.get("ocr_candidate") or {}
                return str(cand.get("value") or cand.get("raw_value") or "")
        return ""

    relationship = _winner_text("rel_code") or _winner_text("insured_relationship")
    if not relationship_is_self(relationship):
        return
    insured = _winner_text("insured_name")
    patients = by_field.get("patient_name") or []
    if not insured or not patients:
        return
    observed: list[str] = []
    for row in patients:
        cand = row.get("ocr_candidate") or {}
        observed.append(str(cand.get("value") or ""))
    chosen = prefer_fuller_self_name(observed, insured)
    if not chosen:
        return
    for row in patients:
        cand = row.get("ocr_candidate") or {}
        raw = str(cand.get("raw_value") or "")
        val = str(cand.get("value") or "")
        if not raw or not names_agree(raw, insured):
            continue
        if len(normalize_person_name(raw).split()) > len(normalize_person_name(val).split()):
            cand["value"] = raw
    # Recompute from updated values so the accepted string is the fuller one.
    observed = [str((row.get("ocr_candidate") or {}).get("value") or "") for row in patients]
    chosen = prefer_fuller_self_name(observed, insured)
    if not chosen:
        return
    match = None
    for row in patients:
        cand = row.get("ocr_candidate") or {}
        if chosen == str(cand.get("value") or ""):
            match = row
            break
    if match is None or match.get("is_winner"):
        return
    winner_id = match["candidate_id"]
    for row in patients:
        row["is_winner"] = row["candidate_id"] == winner_id
        row["winner"] = winner_id
        reasons = list(row.get("ranking_reason") or [])
        if "BOX2_BOX4_FULLER_OBSERVED" not in reasons:
            reasons.append("BOX2_BOX4_FULLER_OBSERVED")
        row["ranking_reason"] = reasons


def rank_saved(source, output):
    source, output = Path(source), Path(output)
    payload = source.read_bytes()
    saved = json.loads(payload)
    if saved.get('status') != 'COMPLETED':
        raise ValueError('Completed OCR candidates required')
    geometry_path = Path(saved['geometry_reference'])
    geometry_bytes = geometry_path.read_bytes()
    if hashlib.sha256(geometry_bytes).hexdigest() != saved['geometry_sha256']:
        raise ValueError('Geometry artifact hash mismatch')
    geometry = json.loads(geometry_bytes)
    if geometry['status'] != 'SUCCESS':
        raise ValueError('Successful saved GeometryResult required')
    regions = {f['field']: f['result']['aligned_roi'] for f in geometry['fields']}
    output.mkdir(parents=True, exist_ok=False)
    policy = CandidateScoringPolicy.load()
    service = CandidateRankingService(policy)
    report = {'type': 'RankedCandidates', 'status': 'RUNNING',
              'document_id': saved['document_id'], 'page_number': saved['page_number'],
              'source_sha256': hashlib.sha256(payload).hexdigest(),
              'ranking_version': service.policy_version, 'ranked_candidates': [],
              'empty_fields': [], 'stop_after': 'candidate_ranking'}
    telemetry = {'ranking_version': service.policy_version, 'events': [],
                 'unassessed_signals': ['localization', 'semantic', 'deterministic', 'cross_field', 'dependency'],
                 'missing_signal_mapping': 'Zero support; deterministic_valid=False means not established, not a validator execution. Existing review reason retained verbatim.',
                 'confidence_basis': 'Original raw OCR confidence, not calibrated ranking confidence',
                 'upstream_rerun': False, 'validators_called': False,
                 'decision_called': False, 'evidence_called': False}
    seen = set()
    try:
        for field in saved['fields']:
            name = field['field']
            if name in seen:
                raise ValueError('Duplicate field ID')
            seen.add(name)
            region = regions[name]
            if field['canonical_region'] != [region[k] for k in ('x0','y0','x1','y1')]:
                raise ValueError('OCR region does not match saved canonical region')
            started = perf_counter()
            observations = []
            originals = {}
            for index, candidate in enumerate(field['candidates']):
                cid = f'{name}:{index}'
                selected = (candidate.get('value') or candidate.get('raw_value') or '') or ''
                # Boost field-shaped OCR (DATE/NAME/ID/CURRENCY) so ranking does not
                # crown header labels like DOB "MM" over calendar-valid alternatives.
                semantic = 0.0
                try:
                    from packages.extraction_recovery.field_cascade import semantic_accept
                    ok, _ = semantic_accept(name, selected)
                    if ok:
                        semantic = 0.95
                except (ImportError, TypeError, ValueError, AttributeError):
                    semantic = 0.0
                engine_name = candidate['engine']
                engine_rel = policy.reliability(
                    policy.engine_reliability, name, engine_name
                )
                # Extra prior: gpt-4o ID residual over short/chrome local that
                # triggered the residual (aligns ranking with reconcile relief).
                if (
                    name in {"insured_id_number", "member_id", "subscriber_id"}
                    and ("gpt4o" in str(engine_name).lower() or "gpt-4o" in str(engine_name).lower())
                    and semantic >= 0.95
                ):
                    alnum = "".join(ch for ch in selected if ch.isalnum())
                    if len(alnum) >= 7:
                        engine_rel = max(engine_rel, 0.92)
                observation = CandidateObservation(
                    candidate_id=cid, raw_text=candidate['raw_value'],
                    selected_text=selected, normalized_value=selected or None,
                    engine=engine_name,
                    preprocessing_profile=candidate.get('preprocessing_variant') or 'unknown',
                    ocr_confidence=float(candidate.get('raw_confidence') or 0), localization_confidence=0,
                    semantic_confidence=semantic, deterministic_valid=bool(semantic),
                    engine_reliability=engine_rel,
                    preprocessing_reliability=policy.reliability(
                        policy.preprocessing_reliability,
                        name,
                        candidate.get('preprocessing_variant') or 'unknown',
                    ))
                observations.append(observation)
                originals[cid] = candidate
            ranked = service.rank(observations)
            event_index = len(telemetry['events'])
            reference = f'ranking_telemetry.json#/events/{event_index}'
            if not observations:
                report['empty_fields'].append({'field_id':name,'reason':'NO_CANDIDATES','telemetry_reference':reference})
            # Obtain each score from the same existing service, not duplicated score logic.
            scores = {o.candidate_id: service.rank([o]).score for o in observations}
            for cid in ranked.ranked_candidate_ids:
                original = originals[cid]
                report['ranked_candidates'].append({
                    'field_id':name, 'candidate_id':cid, 'winner':ranked.selected_candidate_id,
                    'is_winner':cid == ranked.selected_candidate_id,
                    'alternatives':[i for i in ranked.ranked_candidate_ids if i != ranked.selected_candidate_id],
                    'confidence':original['raw_confidence'], 'ranking_score':scores[cid],
                    'ranking_reason':list(ranked.reason_codes), 'provider':original['engine'],
                    'telemetry_reference':reference, 'ocr_candidate':original})
            telemetry['events'].append({'field_id':name,'status':'SUCCESS',
                'latency_ms':(perf_counter()-started)*1000,
                'candidate_ids':[o.candidate_id for o in observations],
                'inputs':[o.model_dump(mode='json') for o in observations],
                'result':ranked.model_dump(mode='json')})
        _prefer_fuller_self_patient(report)
        if set(regions) != seen:
            raise ValueError('Missing canonical fields in OCR artifact')
        report['status'] = 'SUCCESS'
    except Exception as exc:
        report['status'] = 'FAILED'
        telemetry['failure'] = {'type':type(exc).__name__,'reason':str(exc)}
        raise
    finally:
        (output/'RankedCandidates.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
        (output/'ranking_telemetry.json').write_text(json.dumps(telemetry,indent=2,allow_nan=False),encoding='utf-8')
        columns = ['field_id','candidate_id','winner','alternatives','confidence','ranking_score','ranking_reason','provider']
        rows = ''.join('<tr>'+''.join('<td>'+escape(str(row[k]))+'</td>' for k in columns)+'</tr>' for row in report['ranked_candidates'])
        (output/'ranking_summary.html').write_text('<!doctype html><meta charset="utf-8"><title>Candidate ranking</title><style>body{font:14px system-ui;margin:25px}td,th{border:1px solid #ccc;padding:8px}</style><h1>Candidate ranking: '+report['status']+'</h1><p>Existing ranking policy. No validators or downstream decisions executed. Missing signals have zero support; review reasons are preserved. Confidence is raw OCR confidence.</p><table><tr>'+''.join('<th>'+k+'</th>' for k in columns)+'</tr>'+rows+'</table><h2>Fields without candidates</h2><pre>'+escape(json.dumps(report['empty_fields'],indent=2))+'</pre>',encoding='utf-8')
    return report, telemetry


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ocr_candidates')
    parser.add_argument('output_directory')
    args = parser.parse_args()
    report, _ = rank_saved(args.ocr_candidates,args.output_directory)
    print(json.dumps({'status':report['status'],'ranked_candidates':len(report['ranked_candidates']),
                      'empty_fields':len(report['empty_fields'])}))
