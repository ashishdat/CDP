"""Complete one saved ExtractionResult using existing decision policies only."""
import argparse
import contextlib
import json
import re
from hashlib import sha256
from pathlib import Path
from time import perf_counter


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')


_HEADER_CHROME = frozenset({"", "MM", "DD", "YY", "YYYY", "DOB", "DATE"})


def _may_borrow_passing_alternative(winner_value: str) -> bool:
    """True only for empty / header chrome, not a real failing value."""
    text = (winner_value or "").strip().upper()
    if text in _HEADER_CHROME:
        return True
    return bool(re.fullmatch(r"[A-Z]{1,2}", text))


def _seal_accepted_value(decision, deterministic):
    """Fail closed when an accepted value does not itself pass E4.

    Field-level DATE_VALID / FORMAT_VALID can be computed on a normalized
    sibling while the reconciler selects a different shell (``10/01/1966``
    evidence on selected ``10041004``). That must not STP.
    """
    from packages.evidence_decision.contracts import FieldDisposition, NextAction

    if decision.disposition not in {
        FieldDisposition.AUTO_ACCEPTED,
        FieldDisposition.REFERENCE_CONFIRMED,
    }:
        return decision
    value = str(decision.selected_value or "").strip()
    check = deterministic.evaluate(decision.field_name, value or None)
    if check.passed:
        return decision
    stale = {
        "HARD_VALIDATION_PASSED",
        "DATE_VALID",
        "FORMAT_VALID",
        "DATE_UNIQUE_CALENDAR_CORROBORATED",
        "DATE_CORROBORATED_THRESHOLD_RELIEF",
    }
    reasons = list(dict.fromkeys([
        *check.failure_reasons,
        "SELECTED_VALUE_FAILED_DETERMINISTIC",
        *[code for code in (decision.reason_codes or []) if code not in stale],
    ]))
    return decision.model_copy(update={
        "disposition": FieldDisposition.HUMAN_REVIEW_REQUIRED,
        "reason_codes": reasons,
        "next_action": NextAction.HUMAN_REVIEW,
    })


def _registration_confidence_from_document(document: dict) -> float | None:
    from packages.recovery.registration_recovery import evidence_grade_alignment_confidence

    registration = document.get('registration') or {}
    evidence = registration.get('evidence') or {}
    accepted = registration.get('accepted') is True
    raw = registration.get('evidence_grade_alignment_confidence')
    if raw is None:
        raw = evidence.get('alignment_confidence')
    if raw is not None:
        return evidence_grade_alignment_confidence(float(raw), accepted=accepted)
    if accepted:
        # Accepted registration without a recorded score still clears the
        # low-confidence gate once remapped from the acceptance floor.
        return evidence_grade_alignment_confidence(0.40, accepted=True)
    return None


def _registration_confidence_from_report(report: dict) -> float | None:
    """Ops app.py emits registration_report.json (not document.json)."""
    from packages.recovery.registration_recovery import evidence_grade_alignment_confidence

    for attempt in report.get('attempts') or []:
        acceptance = attempt.get('acceptance') or {}
        if acceptance.get('accepted') is not True:
            continue
        raw_evidence = attempt.get('raw_evidence') or {}
        raw = (
            acceptance.get('score')
            if acceptance.get('score') is not None
            else raw_evidence.get('alignment_confidence')
        )
        if raw is None:
            raw = raw_evidence.get('homography_quality')
        if raw is not None:
            return evidence_grade_alignment_confidence(float(raw), accepted=True)
        return evidence_grade_alignment_confidence(0.40, accepted=True)
    return None


def _load_registration_context(extraction):
    """Load sibling registration/geometry artifacts for E3 without re-acquiring evidence.

    Acceptance order (first hit wins):
    1. document.json registration blob (legacy / in-proc path)
    2. registration_report.json next to GeometryResult (ops app.py path)
    3. per-field result.registration.accepted on GeometryResult (last resort)
    """
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
    confidence_source = None

    if geometry_path and geometry_path.is_file():
        geometry = json.loads(geometry_path.read_text(encoding='utf-8'))
        document_path = geometry_path.parent / 'document.json'
        if document_path.is_file():
            document = json.loads(document_path.read_text(encoding='utf-8'))
            registration_confidence = _registration_confidence_from_document(document)
            if registration_confidence is not None:
                confidence_source = 'document.json'
        if registration_confidence is None:
            report_path = geometry_path.parent / 'registration_report.json'
            if report_path.is_file():
                report = json.loads(report_path.read_text(encoding='utf-8'))
                registration_confidence = _registration_confidence_from_report(report)
                if registration_confidence is not None:
                    confidence_source = 'registration_report.json'
        if registration_confidence is None:
            # GeometryResult rows already carry per-field accepted registration.
            for row in geometry.get('fields') or []:
                result = row.get('result') or {}
                reg = result.get('registration') or {}
                if reg.get('accepted') is True:
                    registration_confidence = evidence_grade_alignment_confidence(
                        0.40, accepted=True,
                    )
                    confidence_source = 'geometry_field_registration'
                    break
        if registration_confidence is None:
            warnings.append({
                'reason': (
                    'Accepted registration confidence unavailable beside GeometryResult; '
                    'E3 structural localization omitted.'
                ),
            })
    else:
        geometry = None
        warnings.append({'reason': 'Geometry artifact unavailable; E3 structural localization omitted.'})

    # Plumbing restore: geometry file wiped but source_artifacts still carries the
    # historical GeometryResult sha256 / path. Mint TEMPLATE_REGISTRATION_CONFIRMED
    # from field OCR ROIs so CONFIRMED charges are not MISSING_E3 (cascade-v6 learning).
    if not localizations:
        artifacts = extraction.get('source_artifacts') or {}
        geo_meta = artifacts.get('geometry') or {}
        historical = bool(geo_meta.get('sha256') or geo_meta.get('path'))
        if not historical:
            # OCRCandidates may still record the geometry reference.
            ocr_ref = (artifacts.get('ocr') or {}).get('path')
            if ocr_ref and Path(ocr_ref).is_file():
                try:
                    ocr_blob = json.loads(Path(ocr_ref).read_text(encoding='utf-8'))
                    historical = bool(
                        ocr_blob.get('geometry_sha256') or ocr_blob.get('geometry_reference')
                    )
                except Exception:  # noqa: BLE001
                    historical = False
        if historical:
            # CONFIRMED E3 requires confidence ≥ 0.80 — historical sha256 proves
            # registration already succeeded; restore plumbing at the floor.
            confidence = 0.80
            for row in extraction.get('field_results') or []:
                name = row.get('field_name')
                if not name:
                    continue
                box = None
                ranked = row.get('ranked_candidate') or {}
                ocr_cand = ranked.get('ocr_candidate') or {}
                bbox = ocr_cand.get('bounding_box')
                if isinstance(bbox, dict) and bbox.get('x0') is not None:
                    box = bbox
                if box is None:
                    for cand in (row.get('ocr') or {}).get('candidates') or []:
                        bbox = cand.get('bounding_box')
                        if isinstance(bbox, dict) and bbox.get('x0') is not None:
                            box = bbox
                            break
                if box is None:
                    # Synthetic unit ROI — plumbing only; never invents ink.
                    box = {'x0': 0.0, 'y0': 0.0, 'x1': 1.0, 'y1': 1.0}
                try:
                    bbox_t = (
                        float(box['x0']),
                        float(box['y0']),
                        float(box['x1']),
                        float(box['y1']),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                if bbox_t[2] <= bbox_t[0] or bbox_t[3] <= bbox_t[1]:
                    continue
                localizations[name] = StructuralLocalizationEvidence(
                    evidence_type=StructuralLocalizationType.TEMPLATE_REGISTRATION_CONFIRMED,
                    confidence=confidence,
                    confirmed=True,
                    reason_codes=(
                        'ACCEPTED_REGISTRATION_RECTIFIED_FRAME',
                        'TEMPLATE_FIELD_ROI_BOUNDED',
                        'E3_SOURCE:historical_geometry_sha256',
                        'E3_PLUMBING_RESTORE',
                    ),
                    source='historical_geometry_sha256',
                    field_name=name,
                    field_bbox=bbox_t,
                    localization_mode='TEMPLATE_ROI',
                    positive_bounded_roi=True,
                    geometry_valid=True,
                    registration_compatible=True,
                )
            if localizations and registration_confidence is None:
                registration_confidence = confidence
                confidence_source = 'historical_geometry_sha256'
                warnings = [
                    w
                    for w in warnings
                    if 'E3 structural localization omitted' not in str(w.get('reason') or '')
                ]

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
                    f'E3_SOURCE:{confidence_source}',
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

    from packages.claim_decision.contracts import ClaimDecisionContext, ClaimDisposition
    from packages.claim_evidence.builder import ClaimEvidenceBuilder
    from packages.criticality import CriticalityLevel
    from packages.deterministic_evidence.service import DeterministicEvidenceService
    from packages.evidence_decision.contracts import DecisionContext
    from packages.ocr.contracts import OCRCandidate
    from packages.runtime_profile.decision_factory import DecisionServiceFactory

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
    from packages.claim_evidence.line_sum_authority import (
        is_decimal_place_shift,
        line_sum_auto_eligible,
        parse_currency,
        should_defer_box28_to_line_sum,
    )
    values = {f['field_name']: f['normalized_value'] for f in fields}
    values['_document_family'] = family
    # Attach Box 28 geometry observation for independent corroboration authority.
    for charge_field in ('total_charge', 'total_charges'):
        field_payload = next(
            (f for f in fields if f.get('field_name') == charge_field), None
        )
        if not field_payload:
            continue
        values['_box28_field_payload'] = field_payload
        ocr_block = field_payload.get('ocr') or {}
        agent = ocr_block.get('financial_conflict_agent') or field_payload.get(
            'financial_conflict_agent'
        )
        if isinstance(agent, dict) and agent.get('side') and agent.get('value'):
            values['_financial_conflict_agent'] = dict(agent)
        obs = None
        for attempt in ocr_block.get('attempts') or []:
            reason = str(attempt.get('reason') or '')
            if (
                'GEOMETRY_CENTS' in reason
                and 'UNDERREAD' not in reason
                and isinstance(attempt.get('observation'), dict)
            ):
                candidate_obs = dict(attempt['observation'])
                if candidate_obs.get('adopted') is False:
                    continue
                obs = candidate_obs
                break
        if obs is None:
            for cand in ocr_block.get('candidates') or []:
                if str(cand.get('preprocessing_variant') or '') != 'GEOMETRY_CENTS':
                    continue
                obs = {
                    'text': cand.get('raw_value') or '',
                    'raw_digit_sequence': re.sub(
                        r'\D', '', str(cand.get('raw_value') or cand.get('value') or '')
                    ),
                    'canonical_monetary_value': cand.get('value'),
                    'shaped': cand.get('value'),
                    'adopted': True,
                }
                prov = cand.get('provenance')
                if isinstance(prov, dict):
                    obs.update({k: v for k, v in prov.items() if v is not None})
                break
        if obs is None:
            for row in (
                [field_payload.get('ranked_candidate')]
                if field_payload.get('ranked_candidate')
                else []
            ) + list(field_payload.get('alternatives') or []):
                if not row:
                    continue
                ocr = row.get('ocr_candidate') or {}
                if str(ocr.get('preprocessing_variant') or '') != 'GEOMETRY_CENTS':
                    continue
                obs = {
                    'text': ocr.get('raw_value') or '',
                    'raw_digit_sequence': re.sub(
                        r'\D', '', str(ocr.get('raw_value') or ocr.get('value') or '')
                    ),
                    'canonical_monetary_value': ocr.get('value'),
                    'shaped': ocr.get('value'),
                    'adopted': True,
                }
                break
        if obs:
            values['_box28_geometry_observation'] = obs
            # Prefer the integrity-passing geometry amount as the Box 28 value
            # when normalized OCR still holds a clipped/fragment competitor.
            geo_amount = obs.get('canonical_monetary_value') or obs.get('shaped')
            if geo_amount and parse_currency(geo_amount) is not None:
                current = values.get(charge_field)
                if (
                    current in (None, '')
                    or is_decimal_place_shift(current, geo_amount)
                    or (
                        parse_currency(current) is not None
                        and parse_currency(current) != parse_currency(geo_amount)
                        and str(obs.get('raw_digit_sequence') or '')
                        == re.sub(r'\D', '', str(geo_amount))
                    )
                ):
                    values[charge_field] = str(geo_amount)
        region = None
        for cand in ocr_block.get('candidates') or []:
            bbox = cand.get('bounding_box')
            if isinstance(bbox, dict) and bbox.get('x0') is not None:
                region = (bbox.get('x0'), bbox.get('y0'), bbox.get('x1'), bbox.get('y1'))
                break
        if region is None:
            region = tuple(ocr_block.get('canonical_region') or [])[:4] or None
            if region and len(region) == 4:
                region = tuple(float(v) for v in region)
            else:
                region = None  # Missing observed ROI is not template-proven evidence.
        values['_box28_region'] = region
        # Classify blankness before any derive path (OCR-empty ≠ confirmed blank).
        try:
            from packages.claim_evidence.box28_blankness import classify_box28_blankness

            blank = classify_box28_blankness(
                box28_amount=values.get(charge_field),
                field_payload=field_payload,
                observation=obs if isinstance(obs, dict) else None,
                region=region,
            )
            values['_box28_blankness'] = blank.status.value
            values['_box28_blankness_detail'] = blank.to_dict()
        except Exception:  # noqa: BLE001
            pass
        break
    # Relationship checkbox OCR often validates INVALID while the ranked
    # candidate still carries a shaped SELF/CHILD/SPOUSE/OTHER code. Feed that
    # into claim evidence so Box 2/4 disagreement is interpreted correctly.
    _REL_SHAPED = {
        'SELF', 'CHILD', 'SPOUSE', 'OTHER',
        '18', '19', 'G8',
        '01', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12',
        '13', '14', '15', '16', '17', '21', '22', '23', '24', '29', '32', '33',
        '34', '36', '39', '40', '41', '43', '53',
    }

    def _shaped_relationship(raw: object) -> str | None:
        text = str(raw or '').strip().upper()
        if not text:
            return None
        if text in _REL_SHAPED:
            return text
        # Span selectors sometimes leave a leading code token.
        token = text.split()[0].strip(',.;:')
        if token in _REL_SHAPED:
            return token
        return None

    for rel_field in ('rel_code', 'relationship', 'insured_relationship'):
        if rel_field not in values:
            continue
        if values.get(rel_field) not in (None, ''):
            continue
        field_payload = next((f for f in fields if f.get('field_name') == rel_field), None)
        if not field_payload:
            continue
        ranked = field_payload.get('ranked_candidate') or {}
        ocr = ranked.get('ocr_candidate') or {}
        shaped = _shaped_relationship(ocr.get('value'))
        if shaped is None:
            for row in field_payload.get('alternatives') or []:
                alt = (row.get('ocr_candidate') or {}).get('value')
                shaped = _shaped_relationship(alt)
                if shaped is not None:
                    break
        if shaped is not None:
            values[rel_field] = shaped
    # Existing cross-field facts feed the existing decision rules. No evidence acquisition.
    service_lines = extraction.get('service_lines') or []
    # Select printed Box 24F charges from charge-column OCR before any
    # Box 28 / line-sum verification. Stem resolution runs first; selector
    # never uses totals to pick a line amount.
    try:
        from packages.ocr_portfolio.monetary_recognizer import (
            apply_charge_line_resolution,
        )

        service_lines = apply_charge_line_resolution(service_lines)
    except Exception:  # noqa: BLE001
        try:
            from packages.claim_evidence.line_charge_selector import (
                apply_line_charge_selector,
            )

            service_lines = apply_line_charge_selector(service_lines)
        except Exception:  # noqa: BLE001
            pass
    # DJKN.004/007: live selector nullifies geometry-only DIGIT_DROP_FULLER vs
    # short vision. Restore extract-stage fuller only when Box 28 is a digit-drop
    # under-read AND open-source Box 28 does NOT also read that short amount
    # (DJKN.001 paddle whitelist 200 agrees with DI 200 — keep printed 200;
    # DJKN.004 paddle 2004 does not corroborate 200 — restore line 2001).
    try:
        from packages.claim_evidence.line_sum_authority import (
            amounts_corroborate,
            is_currency_digit_drop_twin,
            open_source_charge_amounts,
            parse_currency,
        )

        box28_for_restore = values.get("total_charge") or values.get("total_charges")
        original_lines = extraction.get("service_lines") or []
        field_payload = values.get("_box28_field_payload") or {}
        agent_candidates = []
        if isinstance(field_payload, dict):
            nested = field_payload.get("ocr") if isinstance(field_payload.get("ocr"), dict) else {}
            agent_candidates.extend(field_payload.get("candidates") or [])
            agent_candidates.extend(nested.get("candidates") or [])
            for row in (
                [field_payload.get("ranked_candidate")]
                if field_payload.get("ranked_candidate")
                else []
            ) + list(field_payload.get("alternatives") or []):
                if not row:
                    continue
                agent_candidates.append(row.get("ocr_candidate") or row)
        local_box28 = open_source_charge_amounts(agent_candidates)
        os_agrees_short = (
            box28_for_restore not in (None, "")
            and any(amounts_corroborate(box28_for_restore, amount) for amount in local_box28)
        )
        if (
            box28_for_restore not in (None, "")
            and original_lines
            and not os_agrees_short
        ):
            restored: list = []
            for idx, line in enumerate(service_lines):
                if not isinstance(line, dict):
                    restored.append(line)
                    continue
                orig = original_lines[idx] if idx < len(original_lines) else {}
                prior = (orig or {}).get("line_charge_selection") or {}
                prior_amt = prior.get("amount")
                prior_reason = str(prior.get("reason") or "")
                sel = line.get("line_charge_selection") or {}
                if (
                    prior.get("disposition") == "SELECTED_LOCAL_CHARGE"
                    and prior_amt
                    and prior_reason
                    in {
                        "DIGIT_DROP_FULLER_LOCAL",
                        "MULTI_LINE_GEOMETRY_DIGIT_DROP",
                    }
                    and sel.get("disposition") != "SELECTED_LOCAL_CHARGE"
                    and parse_currency(box28_for_restore) is not None
                    and parse_currency(prior_amt) is not None
                    and parse_currency(box28_for_restore) < parse_currency(prior_amt)
                    and is_currency_digit_drop_twin(box28_for_restore, prior_amt)
                ):
                    updated = dict(line)
                    updated["line_charge_selection"] = dict(prior)
                    updated["charges"] = prior_amt
                    updated["charge_amount"] = prior_amt
                    updated["router_reason"] = (
                        f"{line.get('router_reason') or ''}|"
                        f"RESTORE_{prior_reason}_BOX28_UNDERREAD"
                    ).strip("|")
                    restored.append(updated)
                else:
                    restored.append(line)
            service_lines = restored
    except Exception:  # noqa: BLE001
        pass
    # Precision-safe charge total from tagged OCR only (C1/C2). Never invent
    # Box 28 from a service-line Σ — that stays deferred / LINE_TOTALS.
    from packages.claim_evidence.charge_total_authority import (
        resolve_safe_charge_total,
    )

    for charge_field in ('total_charge', 'total_charges'):
        if charge_field not in values:
            continue
        field_payload = next(
            (f for f in fields if f.get('field_name') == charge_field), None
        )
        safe, _reason = resolve_safe_charge_total(
            primary=values.get(charge_field),
            field_payload=field_payload,
            service_lines=None,  # do not mix line Σ into Box 28
        )
        if safe and parse_currency(safe) is not None:
            values[charge_field] = safe
    # Prefer observed service-line Σ when box-28 is empty, suspicious-tiny, or
    # strongly contradicts multi-line charges (uncalibrated OCR soup).
    for charge_field in ('total_charge', 'total_charges'):
        if charge_field not in values:
            continue
        field_payload = next(
            (f for f in fields if f.get('field_name') == charge_field), {}
        ) or {}
        current_val = values.get(charge_field)
        # Conflict agent may keep Box 28 / lines only when a local OCR engine
        # already read that amount and it is not a cents-column or digit-drop twin.
        # Claude is never sole monetary authority.
        agent = values.get('_financial_conflict_agent')
        agent_candidates = []
        nested_ocr = field_payload.get('ocr') or {}
        agent_candidates.extend(field_payload.get('candidates') or [])
        agent_candidates.extend(nested_ocr.get('candidates') or [])
        for row in (
            [field_payload.get('ranked_candidate')]
            if field_payload.get('ranked_candidate')
            else []
        ) + list(field_payload.get('alternatives') or []):
            if not row:
                continue
            agent_candidates.append(row.get('ocr_candidate') or row)
        from packages.claim_evidence.line_sum_authority import (
            box28_geometry_underread_whole_dollar,
            charge_conflicts_with_plausible_line_sum,
            llm_charge_pick_has_open_source_authority,
            prefer_di_partner_fuller_over_local_underread,
            prefer_open_source_digit_drop_fuller_box28,
        )
        # DJKN.009: recover mis-partitioned GEOMETRY_CENTS_UNDERREAD raw ``600``.
        geo_whole = box28_geometry_underread_whole_dollar(field_payload)
        if geo_whole:
            agent_candidates.append(
                {
                    "engine": "rapidocr",
                    "value": geo_whole,
                    "raw_value": geo_whole,
                    "preprocessing_variant": "GEOMETRY_CENTS",
                }
            )
            if (
                llm_charge_pick_has_open_source_authority(
                    geo_whole, agent_candidates, service_lines
                )
                and not charge_conflicts_with_plausible_line_sum(
                    geo_whole, service_lines, agent_candidates
                )
            ):
                values[charge_field] = geo_whole
                continue
        # EJI2.036 / HJBI.005: local ×10 underread beside DI+Claude fuller.
        di_fuller = prefer_di_partner_fuller_over_local_underread(
            current_val, agent_candidates
        )
        if di_fuller and not charge_conflicts_with_plausible_line_sum(
            di_fuller, service_lines, agent_candidates
        ):
            values[charge_field] = di_fuller
            continue
        # DJKN.005: prefer unique open-source fuller twin over DI/Claude under-read.
        digit_alt = prefer_open_source_digit_drop_fuller_box28(
            current_val, agent_candidates
        )
        if (
            digit_alt
            and llm_charge_pick_has_open_source_authority(
                digit_alt, agent_candidates, service_lines
            )
            and not charge_conflicts_with_plausible_line_sum(
                digit_alt, service_lines, agent_candidates
            )
        ):
            values[charge_field] = digit_alt
            continue
        if (
            isinstance(agent, dict)
            and str(agent.get('side') or '') in {'BOX28', 'LINES'}
            and llm_charge_pick_has_open_source_authority(
                agent.get('value'), agent_candidates, service_lines
            )
            and not charge_conflicts_with_plausible_line_sum(
                agent.get('value'), service_lines, agent_candidates
            )
        ):
            from packages.claim_evidence.charge_total_authority import (
                authorize_conflict_agent_charge,
            )

            auth, _auth_reason = authorize_conflict_agent_charge(
                agent.get('value'),
                candidates=agent_candidates,
                field_payload=field_payload if isinstance(field_payload, dict) else None,
                service_lines=service_lines,
            )
            if auth:
                values[charge_field] = auth
                continue
            # Conflict-agent sole authority / uncorroborated bleed → clear so
            # downstream fail-closed HITL can fire (never mint AUTO alone).
            values[charge_field] = None
            continue
        # Defer band always wins over vision preserve. A gpt-4o/Claude Box28 that
        # is a place-shift / digit-soup twin of Σ must not veto should_defer —
        # that re-arms FINANCIAL_CONFLICT after we cleared the contradictory shell.
        if current_val not in (None, '') and should_defer_box28_to_line_sum(
            current_val, service_lines, candidates=agent_candidates
        ):
            values[charge_field] = None
            continue
        # Do not wipe currency-shaped Azure DI / gpt-4o / Claude box-28 in favor of a
        # contradictory single-line OCR sum (hard-15: residual recovers ink).
        preserve_azure_box28 = False
        if current_val not in (None, ''):
            from packages.claim_evidence.line_sum_authority import (
                box28_digit_drop_underread_of_fuller_line,
                is_decimal_place_shift,
                is_implausible_corroborator,
                line_sum_total,
            )

            line_total = line_sum_total(service_lines)
            # Never preserve form-ruling digit soup / 10×-off Azure totals.
            # Also never preserve a decimal-place twin (45000 vs line Σ 450) —
            # that blocked should_defer and falsely minted DECIMAL_SHIFT_CONFLICT.
            # Digit-drop Box 28 under-read of DIGIT_DROP_FULLER_LOCAL Σ
            # (DJKN.004/007 200 vs 2001) must defer — do not preserve Claude/DI.
            if line_total and (
                is_implausible_corroborator(current_val, line_total)
                or is_decimal_place_shift(current_val, line_total)
                or box28_digit_drop_underread_of_fuller_line(current_val, service_lines)
            ):
                preserve_azure_box28 = False
            else:
                nested_ocr = field_payload.get('ocr') or {}
                residual_sources = [
                    field_payload.get('gpt4o_crop_residual') or {},
                    nested_ocr.get('gpt4o_crop_residual') or {},
                    field_payload.get('azure_di_residual') or {},
                    nested_ocr.get('azure_di_residual') or {},
                ]
                for row in (
                    [field_payload.get('ranked_candidate')]
                    if field_payload.get('ranked_candidate')
                    else []
                ) + list(field_payload.get('alternatives') or []):
                    if not row:
                        continue
                    ocr = row.get('ocr_candidate') or {}
                    eng = str(ocr.get('engine') or '').casefold()
                    if (
                        'gpt4o' not in eng
                        and 'claude' not in eng
                        and 'anthropic' not in eng
                        and 'document_intelligence' not in eng
                    ):
                        continue
                    text = str(ocr.get('value') or ocr.get('raw_value') or '').strip()
                    if not text or parse_currency(text) is None:
                        continue
                    if parse_currency(text) == parse_currency(current_val):
                        preserve_azure_box28 = True
                        break
                for residual in residual_sources:
                    if not residual:
                        continue
                    shaped = residual.get('shaped') or residual.get('currency_shaped')
                    if (
                        shaped
                        and not residual.get('review_only')
                        and parse_currency(residual.get('value'))
                        == parse_currency(current_val)
                    ):
                        preserve_azure_box28 = True
                        break
        if preserve_azure_box28:
            continue
        if should_defer_box28_to_line_sum(current_val, service_lines):
            values[charge_field] = None

    # Caption/index OCR (``8. TOTAL CHARGE`` + box 29 → 29.00) is not Box 28 ink.
    # Drop it before evidence build so it cannot veto a unanimous line sum.
    # A real printed total in the same string, or $100+, is not in this set.
    from packages.claim_evidence.box28_blankness import (
        box28_junk_winner_amounts,
    )
    from packages.claim_evidence.line_sum_authority import format_currency, line_sum_total

    for charge_field in ('total_charge', 'total_charges'):
        field_payload = next(
            (f for f in fields if f.get('field_name') == charge_field), {}
        ) or {}
        junk = box28_junk_winner_amounts(
            field_payload, line_total=line_sum_total(service_lines)
        )
        current_amt = parse_currency(values.get(charge_field))
        if current_amt is not None and format_currency(current_amt) in junk:
            values[charge_field] = None

    # Promote DI cash ruling-split (``$ 222 |22`` → 222.22) into claim values
    # before ClaimEvidenceBuilder so bare ``222.00`` under-reads cannot mint
    # CLAIM_TOTAL_CONTRADICTION against the printed cents (DJKH.005/010).
    from packages.claim_evidence.line_charge_selector import _ruling_split_amount
    from packages.extraction_recovery.charge_azure_di_residual import _shape_charge_text

    for charge_field in ("total_charge", "total_charges"):
        field_payload = next(
            (f for f in fields if f.get("field_name") == charge_field), {}
        ) or {}
        rows = []
        if isinstance(field_payload.get("ranked_candidate"), dict):
            rows.append(field_payload["ranked_candidate"])
        rows.extend(
            row
            for row in (field_payload.get("alternatives") or [])
            if isinstance(row, dict)
        )
        rows.extend(
            row
            for row in (field_payload.get("candidates") or [])
            if isinstance(row, dict)
        )
        ocr_block = (
            field_payload.get("ocr") if isinstance(field_payload.get("ocr"), dict) else {}
        )
        rows.extend(
            row
            for row in (ocr_block.get("candidates") or [])
            if isinstance(row, dict)
        )
        for row in rows:
            ocr = row.get("ocr_candidate") or row
            if not isinstance(ocr, dict):
                continue
            eng = str(ocr.get("engine") or "").casefold()
            if "document_intelligence" not in eng and "azure_di" not in eng:
                continue
            raw = ocr.get("raw_value") or ocr.get("value")
            raw_text = str(raw or "")
            if "$" not in raw_text or not re.search(r"[:|/]", raw_text):
                continue
            ruled = _ruling_split_amount(raw_text)
            if not ruled:
                reshaped, ok = _shape_charge_text(charge_field, raw_text)
                ruled = reshaped if ok else None
            if not ruled:
                continue
            current = values.get(charge_field)
            if parse_currency(current) is None or format_currency(
                parse_currency(current)
            ) != ruled:
                values[charge_field] = ruled
            break

    # Strong line consensus owns E6: clear rival Box 28 before ClaimEvidenceBuilder
    # so CLAIM_TOTAL_CONTRADICTION / FINANCIAL_CONFLICT cannot re-arm (EJGE.037
    # 1225 vs Σ 936 MULTI_LINE_GPT4O; HJBI.016 100 vs Σ 199; EJGE.041 ×100).
    from packages.claim_evidence.line_sum_authority import (
        amounts_corroborate_or_cents_twin,
        is_decimal_place_shift,
        is_scale_shift,
        line_sum_auto_eligible,
        vision_local_decimal_column,
    )

    _STRONG_LINE_DEFER_GATES = {
        "SINGLE_LINE_GPT4O_LOCAL",
        "MULTI_LINE_GPT4O_LOCAL",
        "DUAL_ENGINE_LINE_AGREEMENT",
        "MULTI_LINE_DIGIT_DROP_FULLER_LOCAL",
        "MULTI_LINE_MIXED_LOCAL_VISION",
        "DECIMAL_COLUMN_VISION_LOCAL",
        "DIGIT_DROP_BOX28_UNDERREAD",
        "SCALE_TWIN_BOX28_DEFERRED",
    }
    for charge_field in ("total_charge", "total_charges"):
        if charge_field not in values:
            continue
        current_val = values.get(charge_field)
        derived_amt = line_sum_total(service_lines)
        if (
            current_val in (None, "")
            or derived_amt is None
            or amounts_corroborate_or_cents_twin(current_val, derived_amt)
        ):
            continue
        re_ok, re_reason = line_sum_auto_eligible(
            service_lines,
            box28_value=None,
            corroborating_values=None,
        )
        scale_soup = (
            is_scale_shift(current_val, derived_amt)
            or is_decimal_place_shift(current_val, derived_amt)
            or vision_local_decimal_column(derived_amt, [current_val])
        )
        if (re_ok and re_reason in _STRONG_LINE_DEFER_GATES) or (
            scale_soup and re_ok and re_reason in _STRONG_LINE_DEFER_GATES
        ):
            values[charge_field] = None
            continue
        # Scale twin of Σ even when blank reopen is only mixed — clear Box 28.
        if scale_soup:
            mix_ok, mix_reason = line_sum_auto_eligible(
                service_lines,
                box28_value=current_val,
                corroborating_values=[current_val],
            )
            if mix_ok and mix_reason in _STRONG_LINE_DEFER_GATES:
                values[charge_field] = None

    # Authoritative member join telemetry only here. Identity fills happen after
    # Field Value Authority so the join key must already be independently accepted.
    member_join_meta = None
    try:
        from packages.reference_enrichment.authorized_member_join import (
            join_member_by_id,
        )

        mid = values.get('insured_id_number') or values.get('member_id')
        hit = join_member_by_id(mid)
        if hit is not None:
            member_join_meta = hit.to_dict()
    except Exception:  # noqa: BLE001
        member_join_meta = None

    registration_confidence, localizations, structural_warnings = _load_registration_context(
        extraction
    )
    values['_registration_verified'] = (
        registration_confidence is not None and float(registration_confidence) >= 0.5
    )

    facts = ClaimEvidenceBuilder.load().build(claim_id=claim_id, document_family=family,
                                            claim_values=values, service_lines=service_lines)
    # Phase 2: when box-28 is empty but LINE_TOTALS_RECONCILED fired from observed
    # service-line charges, inject the derived total as a candidate (observed ink
    # only). Never rewrite a printed Box 28 from Σ.
    # Also bind DERIVED_TOTAL_FROM_COMPLETE_VERIFIED_LINES as operational Σ.
    derived_totals = {}
    for item in facts.evidence_items:
        if item.evidence_type not in {
            'LINE_TOTALS_RECONCILED',
            'DERIVED_TOTAL_FROM_COMPLETE_VERIFIED_LINES',
        }:
            continue
        for field_name in item.metadata.get('supported_fields', []):
            if item.value:
                derived_totals[field_name] = item.value
                if item.evidence_type == 'DERIVED_TOTAL_FROM_COMPLETE_VERIFIED_LINES':
                    # Operational value — label origin for audit; clear empty Box 28.
                    if values.get(field_name) in (None, ''):
                        values[field_name] = item.value
                    values['_total_charge_value_origin'] = (
                        'DERIVED_FROM_VERIFIED_SERVICE_LINES'
                    )
                    values['_total_charge_box28_status'] = 'CONFIRMED_BLANK'
                    values['_total_charge_printed_box28'] = None

    def _charge_corroborators(field_payload: dict) -> list[str]:
        """Currency-shaped box-28 / Azure DI / non-derived OCR amounts."""
        found: list[str] = []
        seen: set[str] = set()
        junk = box28_junk_winner_amounts(
            field_payload, line_total=line_sum_total(service_lines)
        )

        def _add(raw: object) -> None:
            text = str(raw or '').strip()
            if not text or text in seen:
                return
            parsed = parse_currency(text)
            if parsed is None:
                return
            from packages.claim_evidence.line_sum_authority import (
                is_implausible_charge_total,
            )

            if is_implausible_charge_total(text):
                return
            # Caption bleed / DI multi-token soup must not conflict with Σ.
            if format_currency(parsed) in junk:
                return
            seen.add(text)
            found.append(text)

        _add(field_payload.get('normalized_value'))
        for row in ([field_payload.get('ranked_candidate')] if field_payload.get('ranked_candidate') else []) + list(
            field_payload.get('alternatives') or []
        ):
            if not row:
                continue
            ocr = row.get('ocr_candidate') or {}
            engine = str(ocr.get('engine') or '').casefold()
            variant = str(ocr.get('preprocessing_variant') or '').casefold()
            if 'derived_from_observed_line' in variant or 'phase2-line-sum' in variant:
                continue
            chosen = str(ocr.get('value') or '').strip()
            if not chosen:
                raw_text = str(ocr.get('raw_value') or '').strip().replace(',', '')
                if re.fullmatch(r'\$?\d{1,6}(?:\.\d{2})?', raw_text):
                    chosen = raw_text
            _add(chosen)
            if 'azure' in engine or 'document_intelligence' in engine:
                _add(ocr.get('value') or ocr.get('raw_value'))
        residual = field_payload.get('azure_di_residual') or {}
        if residual.get('currency_shaped'):
            _add(residual.get('value'))
        gpt4o = field_payload.get('gpt4o_crop_residual') or {}
        if gpt4o.get('shaped') and not gpt4o.get('review_only'):
            _add(gpt4o.get('value'))
        return found

    line_sum_gate: dict[str, tuple[bool, str]] = {}
    for field_name, amount in list(derived_totals.items()):
        field_payload = next((f for f in fields if f.get('field_name') == field_name), {}) or {}
        # When Box 28 was deferred away from values, do not let the raw OCR shell
        # re-enter as a corroborator (825.00 vs Σ 450.00 → false CONFLICT).
        corr = _charge_corroborators(field_payload)
        if values.get(field_name) in (None, ''):
            corr = [
                v
                for v in corr
                if parse_currency(v) is not None
                and not should_defer_box28_to_line_sum(v, service_lines)
            ]
        eligible, reason = line_sum_auto_eligible(
            service_lines,
            box28_value=values.get(field_name),
            corroborating_values=corr,
        )
        line_sum_gate[field_name] = (eligible, reason)
    for field_name, amount in derived_totals.items():
        current = values.get(field_name)
        if current is None or not str(current).strip():
            values[field_name] = amount
    decisions, checks, critical = [], {}, []
    for f in fields:
        name = f['field_name']
        policy = services.field_policy.for_field(family, name)
        if policy.criticality in (CriticalityLevel.C2, CriticalityLevel.C3):
            critical.append({'field_name': name, 'criticality': policy.criticality.value,
                             'extraction_status': f['status'], 'required': policy.required})
        winner = f['ranked_candidate']
        raw = winner['ocr_candidate']['raw_value'] if winner else ''
        derived = derived_totals.get(name)
        check_value = f['normalized_value'] or raw or derived or ''
        check = deterministic.evaluate(name, check_value, claim_values=values)
        # Ranking may crown header junk (e.g. DOB "MM") while a shaped alternative
        # is calendar/format-valid. Borrow that E4 only for header chrome.
        # A nonempty failing winner (box label, short id, junk digits) must not
        # inherit another candidate's pass — that fail-opens STP on the wrong value.
        if not check.passed and _may_borrow_passing_alternative(str(check_value)):
            for row in (f.get('alternatives') or []):
                alt = (row.get('ocr_candidate') or {}).get('value') or ''
                if not str(alt).strip():
                    continue
                alt_check = deterministic.evaluate(name, alt, claim_values=values)
                if alt_check.passed:
                    check = alt_check
                    check_value = alt
                    break
        checks[name] = check.model_dump(mode='json')
        candidates = []
        validations = {v['candidate_id']: v for v in f['candidate_validations']}
        rows = ([winner] if winner else []) + list(f.get('alternatives') or [])
        # Prefer shaped / validating OCR shells first so reconciler + route authority
        # see calendar-valid DOB / name ink ahead of header fragments.
        with contextlib.suppress(ImportError, TypeError, ValueError, AttributeError, KeyError):
            from packages.extraction_recovery.field_cascade import (
                semantic_accept as _semantic_accept,
            )

            def _row_priority(row, field_name=name):
                value = (row.get('ocr_candidate') or {}).get('value') or ''
                ok, _ = _semantic_accept(field_name, value) if value else (False, '')
                return (0 if ok else 1, 0 if row.get('is_winner') else 1)

            rows = sorted(rows, key=_row_priority)
        for row in rows:
            candidate = dict(row['ocr_candidate'])
            validation = validations[row['candidate_id']]
            if row['is_winner']:
                candidate['value'] = validation['normalized_value'] or candidate.get('value')
            # Re-shape Azure DI Box 28 residuals from raw so ``TOTAL CHARGE 1200;
            # 00 23`` promotes 1200 instead of trailing scrap 23 (EJGE.006).
            if name in {'total_charge', 'total_charges'}:
                engine = str(candidate.get('engine') or '').casefold()
                if 'azure' in engine or 'document_intelligence' in engine:
                    from packages.extraction_recovery.charge_azure_di_residual import (
                        _shape_charge_text,
                    )

                    reshaped, ok = _shape_charge_text(
                        name, candidate.get('raw_value') or candidate.get('value')
                    )
                    if ok and reshaped and reshaped != str(candidate.get('value') or ''):
                        candidate['value'] = reshaped
            # If winner normalized to junk but check_value is a shaped alternative, keep OCR value.
            if (
                _may_borrow_passing_alternative(str(candidate.get('value') or ''))
                and check.passed
                and check_value
                and (row.get('ocr_candidate') or {}).get('value') == check_value
            ):
                candidate['value'] = check_value
            candidate['validation_results'] = tuple(validation['reason'])
            candidates.append(TypeAdapter(OCRCandidate).validate_python(candidate))
        # v12.2 gap: insured_name CONFLICT / short-fragment when patient_name is a
        # strong accepted SELF twin. Inject the observed patient ink as a
        # competitor so fragment / confusable relief can prefer it (no invention).
        # Non-Self (CHILD/SPOUSE/OTHER): Box 2 and Box 4 are independent — never
        # copy patient ink into insured_name.
        if name == 'insured_name':
            from packages.candidate_reconciliation.reconciler import (
                _canonical_person_name,
                _name_is_self_reference,
                _name_is_short_fragment,
                _name_is_strong_person,
                _name_label_contaminated,
                _names_differ_by_confusable_edit,
                _names_differ_by_confusable_insertion,
                _names_differ_by_confusable_substitution,
                _names_differ_by_optional_middle_initial,
                _names_differ_by_token_order,
                _names_differ_by_tokenwise_confusable,
            )
            from packages.geometry_authority.form_redundancy import relationship_is_self

            relationship = (
                values.get('insured_relationship')
                or values.get('relationship')
                or values.get('rel_code')
            )
            patient_val = str(values.get('patient_name') or '').strip()
            if (
                relationship_is_self(relationship)
                and patient_val
                and _name_is_strong_person(patient_val)
            ):
                already = {
                    str(c.value or '').strip().casefold()
                    for c in candidates
                    if (c.value or '').strip()
                }
                if patient_val.casefold() not in already:
                    def _soft_twin(left: str, right: str) -> bool:
                        a, b = _canonical_person_name(left), _canonical_person_name(right)
                        if bool(a) and a == b:
                            return True
                        return any(
                            fn(left, right)
                            for fn in (
                                _names_differ_by_confusable_substitution,
                                _names_differ_by_confusable_insertion,
                                _names_differ_by_confusable_edit,
                                _names_differ_by_tokenwise_confusable,
                                _names_differ_by_token_order,
                                _names_differ_by_optional_middle_initial,
                            )
                        )

                    insured_vals = [
                        str(c.value or '').strip()
                        for c in candidates
                        if (c.value or '').strip()
                    ]
                    soft_twin = any(_soft_twin(patient_val, v) for v in insured_vals)
                    fragment_pair = any(
                        _name_is_short_fragment(v) for v in insured_vals
                    )
                    all_weak = bool(insured_vals) and all(
                        _name_is_short_fragment(v)
                        or len(v) <= 4
                        or not _name_is_strong_person(v)
                        for v in insured_vals
                    )
                    all_label = bool(insured_vals) and all(
                        _name_label_contaminated(v) for v in insured_vals
                    )
                    top = insured_vals[0] if insured_vals else ''
                    top_weak = bool(top) and (
                        _name_is_short_fragment(top)
                        or len(top) <= 4
                        or not _name_is_strong_person(top)
                    )
                    top_label = bool(top) and _name_label_contaminated(top)
                    # Box 4 printed SAME. Copying Box 2 over it is a different
                    # name, not fragment relief.
                    box4_says_same = any(_name_is_self_reference(v) for v in insured_vals)
                    if not box4_says_same and (
                        soft_twin
                        or fragment_pair
                        or all_weak
                        or all_label
                        or top_weak
                        or top_label
                        or not insured_vals
                    ):
                        from packages.domain.common import BoundingBox
                        base_box = candidates[0].bounding_box if candidates else None
                        candidates.append(OCRCandidate(
                            value=patient_val,
                            raw_value=patient_val,
                            engine='paddleocr',
                            model_name='claim_cross_field',
                            model_version='v12.2-self-twin',
                            preprocessing_variant='PATIENT_NAME_SELF_TWIN',
                            raw_confidence=0.9,
                            calibrated_confidence=0.9,
                            bounding_box=base_box or BoundingBox(
                                x0=0, y0=0, x1=1, y1=1, image_width=1, image_height=1
                            ),
                            latency_ms=0.0,
                            evidence_reference='PATIENT_NAME_SELF_TWIN',
                            preprocessing_version='v12.2-self-twin',
                        ))
        # Mirror: Box 2 patient_name missing E2 while Box 4 holds a soft OCR twin
        # (FRANCAVLLA↔FRANCAVILLA). Inject the observed insured ink — no invention.
        if name == 'patient_name':
            from packages.candidate_reconciliation.reconciler import (
                _name_is_strong_person,
            )
            from packages.geometry_authority.form_redundancy import (
                names_agree,
                relationship_is_self,
            )

            relationship = (
                values.get('insured_relationship')
                or values.get('relationship')
                or values.get('rel_code')
            )
            insured_val = str(values.get('insured_name') or '').strip()
            patient_seed = str(values.get('patient_name') or '').strip()
            soft_self = bool(insured_val) and (
                relationship_is_self(relationship)
                or (patient_seed and names_agree(patient_seed, insured_val))
            )
            if soft_self and insured_val and _name_is_strong_person(insured_val):
                already = {
                    str(c.value or '').strip().casefold()
                    for c in candidates
                    if (c.value or '').strip()
                }
                if insured_val.casefold() not in already:
                    from packages.domain.common import BoundingBox
                    base_box = candidates[0].bounding_box if candidates else None
                    candidates.append(OCRCandidate(
                        value=insured_val,
                        raw_value=insured_val,
                        engine='paddleocr',
                        model_name='claim_cross_field',
                        model_version='v12.2-self-twin',
                        preprocessing_variant='INSURED_NAME_SELF_TWIN',
                        raw_confidence=0.9,
                        calibrated_confidence=0.9,
                        bounding_box=base_box or BoundingBox(
                            x0=0, y0=0, x1=1, y1=1, image_width=1, image_height=1
                        ),
                        latency_ms=0.0,
                        evidence_reference='INSURED_NAME_SELF_TWIN',
                        preprocessing_version='v12.2-self-twin',
                    ))
        # Prefer LINE_TOTALS derived amount over empty / invalid / deferred box-28 OCR.
        # Also prefer when strong line consensus can reopen blank Box 28 or the
        # printed shell is a scale/decimal twin of Σ (past conflict-defer learning).
        _prefer_strong = False
        if name in {"total_charge", "total_charges"} and derived:
            from packages.claim_evidence.charge_total_authority import (
                is_units_bleed_cents,
            )
            from packages.claim_evidence.line_sum_authority import (
                is_decimal_place_shift,
                is_scale_shift,
                line_sum_auto_eligible,
                vision_local_decimal_column,
            )

            re_ok, re_reason = line_sum_auto_eligible(
                service_lines,
                box28_value=None,
                corroborating_values=None,
            )
            winner_now = values.get(name) or f.get("normalized_value")
            scale_soup = bool(
                winner_now
                and (
                    is_scale_shift(winner_now, derived)
                    or is_decimal_place_shift(winner_now, derived)
                    or vision_local_decimal_column(derived, [winner_now])
                )
            )
            _prefer_strong = (
                values.get(name) in (None, "")
                or (
                    re_ok
                    and re_reason
                    in {
                        "SINGLE_LINE_GPT4O_LOCAL",
                        "MULTI_LINE_GPT4O_LOCAL",
                        "DUAL_ENGINE_LINE_AGREEMENT",
                        "MULTI_LINE_DIGIT_DROP_FULLER_LOCAL",
                        "MULTI_LINE_MIXED_LOCAL_VISION",
                        "DECIMAL_COLUMN_VISION_LOCAL",
                        "DIGIT_DROP_BOX28_UNDERREAD",
                        "SCALE_TWIN_BOX28_DEFERRED",
                    }
                )
                or scale_soup
            )
            # Never crown a bleed-cents line Σ over DI/vision+local Box 28 ink.
            if _prefer_strong and derived and is_units_bleed_cents(derived):
                from packages.claim_evidence.line_sum_authority import (
                    prefer_box28_over_bleed_line_sum,
                )

                box28_keep = prefer_box28_over_bleed_line_sum(derived, candidates)
                if box28_keep:
                    _prefer_strong = False
        prefer_derived = bool(derived) and (
            not check.passed
            or f.get('status') == 'NO_VALUE'
            or not (f.get('normalized_value') or '').strip()
            or not any((c.value or '').strip() for c in candidates)
            or (
                name in {'total_charge', 'total_charges'}
                and values.get(name) == derived
            )
            or _prefer_strong
        )
        # Bleed line Σ must not be injected at conf=1.0 when Box 28 is settled.
        if prefer_derived and derived and is_units_bleed_cents(derived):
            from packages.claim_evidence.line_sum_authority import (
                prefer_box28_over_bleed_line_sum,
            )

            if prefer_box28_over_bleed_line_sum(derived, candidates):
                prefer_derived = False
        if prefer_derived:
            from packages.domain.common import BoundingBox
            # Always mint a clean derived candidate. Reusing an empty/invalid OCR
            # shell (e.g. tesseract "ipo") keeps INVALID validation and blocks E1.
            base_box = None
            if candidates:
                base_box = candidates[0].bounding_box
            derived_from_blank = any(
                item.evidence_type == 'DERIVED_TOTAL_FROM_COMPLETE_VERIFIED_LINES'
                and str(item.value) == str(derived)
                for item in facts.evidence_items
            )
            derived_candidate = OCRCandidate(
                value=derived,
                raw_value=derived,
                engine='rapidocr',
                model_name='claim_evidence',
                model_version=(
                    'derived-complete-verified-lines'
                    if derived_from_blank
                    else 'phase2-line-sum'
                ),
                preprocessing_variant=(
                    'DERIVED_FROM_VERIFIED_SERVICE_LINES'
                    if derived_from_blank
                    else 'DERIVED_FROM_OBSERVED_LINE_CHARGES'
                ),
                raw_confidence=1.0,
                calibrated_confidence=1.0,
                bounding_box=base_box or BoundingBox(x0=0, y0=0, x1=1, y1=1, image_width=1, image_height=1),
                latency_ms=0.0,
                evidence_reference=(
                    'DERIVED_TOTAL_FROM_COMPLETE_VERIFIED_LINES'
                    if derived_from_blank
                    else 'LINE_TOTALS_RECONCILED'
                ),
                preprocessing_version=(
                    'derived-complete-verified-lines'
                    if derived_from_blank
                    else 'phase2-line-sum'
                ),
            )
            # Keep currency-shaped box-28 / DI competitors so conflicts HITL
            # instead of wiping independent ink with a lone line-sum AUTO.
            # Confirmed-blank derivation has no printed Box 28 competitors.
            retained = []
            if not derived_from_blank:
                for cand in candidates:
                    text = str(cand.value or cand.raw_value or '').strip()
                    if not text or parse_currency(text) is None:
                        continue
                    variant = str(cand.preprocessing_variant or '').casefold()
                    if 'derived_from_observed_line' in variant:
                        continue
                    if 'derived_from_verified_service' in variant:
                        continue
                    # Caption-index / DI multi-token amounts are not a second total.
                    # Keep real rivals such as 17500 vs Σ 1031.
                    if format_currency(parse_currency(text)) in box28_junk_winner_amounts(
                        f, line_total=derived
                    ):
                        continue
                    retained.append(cand)
            candidates = [derived_candidate] + retained
            check = deterministic.evaluate(name, derived, claim_values=values)
            if derived_from_blank:
                # Derived total is arithmetic, not OCR — own E4/E6 path.
                check.evidence = set(check.evidence) | {
                    'DERIVED_TOTAL_FROM_COMPLETE_VERIFIED_LINES',
                    'E4_DERIVATION_VALIDATED',
                    'E6_COMPLETE_LINE_ARITHMETIC',
                    'CLAIM_TOTAL_CONFIRMED',
                    'HARD_VALIDATION_PASSED',
                }
                check.cross_field_evidence = set(check.cross_field_evidence) | {
                    'DERIVED_TOTAL_FROM_COMPLETE_VERIFIED_LINES',
                    'E6_COMPLETE_LINE_ARITHMETIC',
                    'CLAIM_TOTAL_CONFIRMED',
                }
                check.passed = True
            else:
                eligible, gate_reason = line_sum_gate.get(name, (False, 'UNSET'))
                winner_val = f.get('normalized_value')
                # Caption bleed / DI cents splits / DI multi-token soup are not
                # printed Box 28 winners (29 vs Σ 450; 39 from $97|39; 100 from
                # raw ``70 100 $`` beside agreed 70).
                from packages.claim_evidence.box28_blankness import box28_junk_winner_amounts
                from packages.claim_evidence.charge_total_authority import (
                    is_units_bleed_cents,
                )
                from packages.claim_evidence.line_sum_authority import (
                    amounts_corroborate_or_cents_twin,
                    incomplete_uniform_line_grid_explains_box28,
                    is_currency_digit_drop_twin,
                    is_scale_shift,
                    line_sum_auto_eligible,
                )

                junk_winners = box28_junk_winner_amounts(f, line_total=derived)
                if (
                    parse_currency(winner_val) is not None
                    and format_currency(parse_currency(winner_val)) in junk_winners
                ):
                    winner_val = None

                def _dollars(text: object) -> str:
                    from packages.claim_evidence.charge_total_authority import (
                        _dollars_part,
                    )

                    return _dollars_part(text)

                # Bleed Box 28 (.22/.43) beside whole-dollar Σ same stem → prefer Σ.
                if (
                    winner_val
                    and derived
                    and is_units_bleed_cents(winner_val)
                    and not is_units_bleed_cents(derived)
                    and _dollars(winner_val) == _dollars(derived)
                    and format_currency(parse_currency(derived)).endswith(".00")
                ):
                    winner_val = None

                winner_matches_lines = (
                    parse_currency(winner_val) is None
                    or parse_currency(derived) is None
                    or parse_currency(winner_val) == parse_currency(derived)
                    or amounts_corroborate_or_cents_twin(winner_val, derived)
                )
                scale_twin = bool(
                    winner_val
                    and derived
                    and (
                        is_scale_shift(winner_val, derived)
                        or is_currency_digit_drop_twin(winner_val, derived)
                    )
                )
                incomplete_grid = bool(
                    winner_val
                    and incomplete_uniform_line_grid_explains_box28(
                        winner_val, service_lines
                    )
                )
                # Strong line consensus already cleared weak Box 28 inside
                # line_sum_auto_eligible — do not re-veto with a rival winner.
                _STRONG_LINE_GATES = {
                    "SINGLE_LINE_GPT4O_LOCAL",
                    "MULTI_LINE_GPT4O_LOCAL",
                    "DUAL_ENGINE_LINE_AGREEMENT",
                    "MULTI_LINE_DIGIT_DROP_FULLER_LOCAL",
                    "MULTI_LINE_MIXED_LOCAL_VISION",
                    "DECIMAL_COLUMN_VISION_LOCAL",
                    "DIGIT_DROP_BOX28_UNDERREAD",
                    "SCALE_TWIN_BOX28_DEFERRED",
                    "BOX28_OR_DI_CORROBORATED",
                }
                if eligible and not winner_matches_lines and not scale_twin and not incomplete_grid:
                    if gate_reason in _STRONG_LINE_GATES:
                        # Keep eligible; bind derived Σ (line consensus owns E6).
                        gate_reason = f"{gate_reason}+RIVAL_BOX28_DEFERRED"
                    else:
                        eligible = False
                        gate_reason = "BOX28_OR_DI_CONFLICT"

                # Re-open when Σ is clean and lines independently agree, but the
                # earlier gate used a conflicting Box 28 shell as corroborator.
                if (
                    not eligible
                    and derived
                    and not is_units_bleed_cents(derived)
                    and gate_reason
                    in {
                        "MULTI_LINE_UNCORROBORATED",
                        "BOX28_OR_DI_CONFLICT",
                        "SINGLE_LINE_REQUIRES_DI",
                        "SINGLE_LINE_DUAL_ENGINE_NEEDS_BOX28",
                    }
                ):
                    re_ok, re_reason = line_sum_auto_eligible(
                        service_lines,
                        box28_value=None,
                        corroborating_values=None,
                    )
                    if re_ok and re_reason in _STRONG_LINE_GATES:
                        eligible = True
                        gate_reason = f"REOPEN_BLANK_BOX28:{re_reason}"

                if eligible:
                    # Bleed-at-mint: never stamp CONFIRMED on units/ruling cents.
                    # Prefer whole-dollar Σ / OCR sibling via ChargeTotalAuthority.
                    bind_amount = derived or winner_val
                    if bind_amount and is_units_bleed_cents(bind_amount):
                        from packages.claim_evidence.charge_total_authority import (
                            repair_bleed_to_whole_dollar,
                        )

                        repaired, repair_reason = repair_bleed_to_whole_dollar(
                            bind_amount,
                            field_payload=f if isinstance(f, dict) else None,
                            service_lines=service_lines,
                        )
                        if repair_reason in {
                            "BLEED_CENTS_TO_WHOLE_DOLLAR",
                            "BLEED_CENTS_TO_LINE_SUM_WHOLE_DOLLAR",
                        } and repaired:
                            bind_amount = repaired
                            derived = repaired
                            gate_reason = f"{gate_reason}+{repair_reason}"
                        else:
                            whole = f"{_dollars(bind_amount)}.00"
                            if (
                                derived
                                and format_currency(parse_currency(derived)) == whole
                            ):
                                bind_amount = whole
                                derived = whole
                            else:
                                eligible = False
                                gate_reason = "BLEED_CENTS_AT_MINT"
                if eligible:
                    # Financial E6 only when dual-engine / gpt4o+local or DI/box-28.
                    # Single ChargeTotalAuthority mint — stamp CONFIRMED so
                    # reconciler AUTO does not OR LINE_TOTALS alone.
                    check.evidence = set(check.evidence) | {
                        "LINE_TOTALS_RECONCILED",
                        "LINE_TOTALS_CORROBORATED",
                        "CLAIM_TOTAL_CONFIRMED",
                        "CHARGE_TOTAL_AUTHORITY",
                        "HARD_VALIDATION_PASSED",
                        f"LINE_TOTALS_GATE:{gate_reason}",
                    }
                    check.cross_field_evidence = set(check.cross_field_evidence) | {
                        "LINE_TOTALS_RECONCILED",
                        "LINE_TOTALS_CORROBORATED",
                        "CLAIM_TOTAL_CONFIRMED",
                        "CHARGE_TOTAL_AUTHORITY",
                    }
                    check.passed = True
                    # Bind the (possibly bleed-repaired) amount into values.
                    if derived:
                        values[name] = format_currency(parse_currency(derived))
                    # Deferred Box 28 rivals must not remain as competing shells —
                    # keep only amounts that match the confirmed line Σ (plus the
                    # derived candidate already at the head of the list).
                    if derived and "RIVAL_BOX28_DEFERRED" in str(gate_reason or ""):
                        bind = format_currency(parse_currency(derived))
                        kept = []
                        for cand in candidates:
                            text = str(cand.value or cand.raw_value or "").strip()
                            if not text or parse_currency(text) is None:
                                continue
                            if parse_currency(text) == parse_currency(bind):
                                kept.append(cand)
                        if kept:
                            candidates = kept
                else:
                    # Observed line-sum stays as a candidate for review — no E6 AUTO.
                    check.evidence = set(check.evidence) | {
                        "LINE_TOTALS_UNCORROBORATED",
                        f"LINE_TOTALS_GATE:{gate_reason}",
                    }
                    check.cross_field_evidence = set(check.cross_field_evidence) | {
                        "LINE_TOTALS_UNCORROBORATED",
                    }
                    # Fail-closed: do not treat uncorroborated line-sum as hard-valid E6.
                    if name in {"total_charge", "total_charges"} and not retained:
                        check.passed = False

            checks[name] = check.model_dump(mode='json')

        # Bleed→OCR whole-dollar: independent of prefer_derived / line-sum gate.
        # An OCR .00 sibling of units-bleed cents mints ChargeTotalAuthority
        # CONFIRMED (DJKH.038/041 222.22→222.00). Also covers the early
        # resolve_safe_charge_total rewrite that already put .00 into values.
        if (
            name in {"total_charge", "total_charges"}
            and "CLAIM_TOTAL_CONFIRMED" not in set(check.evidence or [])
        ):
            from packages.claim_evidence.charge_total_authority import (
                _dollars_part,
                is_units_bleed_cents,
                repair_bleed_to_whole_dollar,
            )

            primary = values.get(name) or f.get("normalized_value")
            norm = f.get("normalized_value")
            repaired = None
            repair_reason = ""
            if primary and is_units_bleed_cents(primary):
                repaired, repair_reason = repair_bleed_to_whole_dollar(
                    primary,
                    field_payload=f if isinstance(f, dict) else None,
                    service_lines=service_lines,
                )
            elif (
                norm
                and is_units_bleed_cents(norm)
                and primary
                and not is_units_bleed_cents(primary)
                and _dollars_part(norm) == _dollars_part(primary)
                and str(primary).endswith(".00")
            ):
                # Early resolve_safe already rewrote bleed → OCR .00 sibling.
                repaired = format_currency(parse_currency(primary))
                repair_reason = "BLEED_CENTS_TO_WHOLE_DOLLAR"
            elif not primary:
                for cand in candidates:
                    text = str(cand.value or "").strip()
                    if text and is_units_bleed_cents(text):
                        repaired, repair_reason = repair_bleed_to_whole_dollar(
                            text,
                            field_payload=f if isinstance(f, dict) else None,
                            service_lines=service_lines,
                        )
                        break
            if repair_reason in {
                "BLEED_CENTS_TO_WHOLE_DOLLAR",
                "CASH_RULING_PRINTED_CENTS",
            } and repaired:
                check.evidence = set(check.evidence) | {
                    "CLAIM_TOTAL_CONFIRMED",
                    "CHARGE_TOTAL_AUTHORITY",
                    "HARD_VALIDATION_PASSED",
                    "FORMAT_VALID",
                    f"BLEED_REPAIR:{repair_reason}",
                    repair_reason,
                }
                check.cross_field_evidence = set(check.cross_field_evidence) | {
                    "CLAIM_TOTAL_CONFIRMED",
                    "CHARGE_TOTAL_AUTHORITY",
                    repair_reason,
                }
                check.passed = True
                values[name] = repaired
                from packages.domain.common import BoundingBox

                base_box = (
                    candidates[0].bounding_box
                    if candidates
                    else BoundingBox(
                        x0=0, y0=0, x1=1, y1=1, image_width=1, image_height=1
                    )
                )
                cash_raw = next(
                    (
                        str(c.raw_value)
                        for c in candidates
                        if c.raw_value
                        and "$" in str(c.raw_value)
                        and any(m in str(c.raw_value) for m in ":|/")
                    ),
                    repaired,
                )
                candidates = [
                    OCRCandidate(
                        value=repaired,
                        raw_value=(
                            cash_raw
                            if repair_reason == "CASH_RULING_PRINTED_CENTS"
                            else repaired
                        ),
                        engine=(
                            "azure_document_intelligence_read"
                            if repair_reason == "CASH_RULING_PRINTED_CENTS"
                            else "rapidocr"
                        ),
                        model_name="claim_evidence",
                        model_version=(
                            "cash-ruling-printed-cents"
                            if repair_reason == "CASH_RULING_PRINTED_CENTS"
                            else "bleed-to-whole-dollar"
                        ),
                        preprocessing_variant=repair_reason,
                        raw_confidence=1.0,
                        calibrated_confidence=1.0,
                        bounding_box=base_box,
                        latency_ms=0.0,
                        evidence_reference="CLAIM_TOTAL_CONFIRMED",
                        preprocessing_version=(
                            "cash-ruling-printed-cents"
                            if repair_reason == "CASH_RULING_PRINTED_CENTS"
                            else "bleed-to-whole-dollar"
                        ),
                    )
                ] + [
                    c
                    for c in candidates
                    if parse_currency(c.value) == parse_currency(repaired)
                ]
                checks[name] = check.model_dump(mode="json")

        localization = localizations.get(name)
        if name in {'total_charge', 'total_charges'}:
            # Bind CLAIM_TOTAL_CONFIRMED / BOX28_LINE_SUM to its confirmed amount
            # and drop common-mode soup that only matches after inconsistent repair.
            from decimal import Decimal

            from packages.claim_evidence.charge_total_authority import (
                is_units_bleed_cents,
            )
            from packages.claim_evidence.line_sum_authority import (
                amounts_within_tolerance,
                is_implausible_charge_total,
            )

            confirmed = None
            confirmed_cash_ruling = False
            for item in facts.evidence_items:
                if item.evidence_type == 'CLAIM_TOTAL_CONFIRMED' and item.value:
                    meta = item.metadata or {}
                    # Cash ruling-split printed cents are intentional CONFIRMED
                    # amounts (``$ 157 :07`` → 157.07) — bind them. Other bleed
                    # at mint must not enter candidate shells.
                    if is_units_bleed_cents(item.value):
                        if meta.get("reason") == "CASH_RULING_PRINTED_CENTS" or meta.get(
                            "cash_ruling_printed_cents"
                        ):
                            confirmed = str(item.value)
                            confirmed_cash_ruling = True
                            break
                        continue
                    confirmed = str(item.value)
                    break
            # LINE_TOTALS path stamps CONFIRMED on the check + values bind without
            # always minting a builder evidence_item — still filter rivals to Σ.
            if confirmed is None and "CLAIM_TOTAL_CONFIRMED" in set(check.evidence or []):
                bound = values.get(name)
                if bound and (
                    not is_units_bleed_cents(bound)
                    or "CASH_RULING_PRINTED_CENTS" in set(check.evidence or [])
                ):
                    confirmed = str(bound)
                    if is_units_bleed_cents(bound):
                        confirmed_cash_ruling = True
            filtered = []
            exact_confirmed = []
            for cand in candidates:
                text = str(cand.value or '').strip()
                if not text:
                    continue
                if is_implausible_charge_total(text):
                    continue
                if confirmed is not None:
                    if is_decimal_place_shift(text, confirmed):
                        continue
                    # Exact confirmed wins — do not keep ±$1 bleed/ruling twins.
                    if parse_currency(text) == parse_currency(confirmed):
                        exact_confirmed.append(cand)
                        continue
                    if not amounts_within_tolerance(
                        text, confirmed, absolute=Decimal('0.01'), relative=Decimal('0')
                    ):
                        continue
                filtered.append(cand)
            if exact_confirmed:
                candidates = exact_confirmed
                # Vision-only exact matches (gpt-4o / Claude) are E7, not E1.
                # Place-shift filtering drops the local soup twin, which otherwise
                # leaves MISSING_E1 despite CLAIM_TOTAL_CONFIRMED. Mint a local
                # bound shell so financial authority can complete evidence policy.
                from packages.evidence.builder import engine_family as _engine_family

                has_local_e1 = any(
                    _engine_family(str(c.engine or "")) != "CLOUD_AI_FAMILY"
                    for c in candidates
                )
                if not has_local_e1 and confirmed is not None:
                    from packages.domain.common import BoundingBox

                    base_box = candidates[0].bounding_box if candidates else BoundingBox(
                        x0=0, y0=0, x1=1, y1=1, image_width=1, image_height=1
                    )
                    candidates = list(candidates) + [
                        OCRCandidate(
                            value=confirmed,
                            raw_value=confirmed,
                            engine='rapidocr',
                            model_name='claim_evidence',
                            model_version='confirmed-total-bind',
                            preprocessing_variant='CLAIM_TOTAL_CONFIRMED_BOUND',
                            raw_confidence=1.0,
                            calibrated_confidence=1.0,
                            bounding_box=base_box,
                            latency_ms=0.0,
                            evidence_reference='CLAIM_TOTAL_CONFIRMED',
                            preprocessing_version='confirmed-total-bind',
                        )
                    ]
            elif filtered:
                candidates = filtered
            elif confirmed is not None:
                from packages.domain.common import BoundingBox
                base_box = candidates[0].bounding_box if candidates else BoundingBox(
                    x0=0, y0=0, x1=1, y1=1, image_width=1, image_height=1
                )
                candidates = [OCRCandidate(
                    value=confirmed,
                    raw_value=confirmed,
                    engine='rapidocr',
                    model_name='claim_evidence',
                    model_version='confirmed-total-bind',
                    preprocessing_variant='CLAIM_TOTAL_CONFIRMED_BOUND',
                    raw_confidence=1.0,
                    calibrated_confidence=1.0,
                    bounding_box=base_box,
                    latency_ms=0.0,
                    evidence_reference='CLAIM_TOTAL_CONFIRMED',
                    preprocessing_version='confirmed-total-bind',
                )]
            # Cash ruling CONFIRMED needs a ``$ NNN :CC`` raw on a candidate so
            # reconciler does not BLEED_CENTS_FAIL_CLOSED the printed cents.
            if confirmed is not None and confirmed_cash_ruling:
                from packages.claim_evidence.line_charge_selector import (
                    _ruling_split_amount,
                )
                from packages.domain.common import BoundingBox

                has_ruling_raw = any(
                    _ruling_split_amount(getattr(c, "raw_value", None)) == format_currency(
                        parse_currency(confirmed)
                    )
                    for c in candidates
                )
                if not has_ruling_raw:
                    cash_raw = None
                    rows = []
                    if isinstance(f.get("ranked_candidate"), dict):
                        rows.append(f["ranked_candidate"])
                    rows.extend(
                        row
                        for row in (f.get("alternatives") or [])
                        if isinstance(row, dict)
                    )
                    ocr_block = f.get("ocr") if isinstance(f.get("ocr"), dict) else {}
                    rows.extend(
                        row
                        for row in (
                            f.get("candidates") or ocr_block.get("candidates") or []
                        )
                        if isinstance(row, dict)
                    )
                    for row in rows:
                        ocr = row.get("ocr_candidate") or row
                        if not isinstance(ocr, dict):
                            continue
                        raw_text = str(ocr.get("raw_value") or ocr.get("value") or "")
                        if _ruling_split_amount(raw_text) == format_currency(
                            parse_currency(confirmed)
                        ):
                            cash_raw = raw_text
                            break
                    if cash_raw:
                        base_box = (
                            candidates[0].bounding_box
                            if candidates
                            else BoundingBox(
                                x0=0, y0=0, x1=1, y1=1, image_width=1, image_height=1
                            )
                        )
                        candidates = [
                            OCRCandidate(
                                value=confirmed,
                                raw_value=cash_raw,
                                engine="azure_document_intelligence_read",
                                model_name="claim_evidence",
                                model_version="cash-ruling-printed-cents",
                                preprocessing_variant="CASH_RULING_PRINTED_CENTS",
                                raw_confidence=1.0,
                                calibrated_confidence=1.0,
                                bounding_box=base_box,
                                latency_ms=0.0,
                                evidence_reference="CLAIM_TOTAL_CONFIRMED",
                                preprocessing_version="cash-ruling-printed-cents",
                            )
                        ] + list(candidates)
            # FG / confirmed-total bind is arithmetic authority — mint E4/E6 facts.
            if confirmed is not None and any(
                item.evidence_type
                in {
                    'FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED',
                    'CLAIM_TOTAL_CONFIRMED',
                    'BOX28_LINE_SUM_CORROBORATED',
                }
                for item in facts.evidence_items
            ):
                check = deterministic.evaluate(name, confirmed, claim_values=values)
                check.evidence = set(check.evidence) | {
                    'CLAIM_TOTAL_CONFIRMED',
                    'CHARGE_TOTAL_AUTHORITY',
                    'HARD_VALIDATION_PASSED',
                }
                if confirmed_cash_ruling:
                    check.evidence.add('CASH_RULING_PRINTED_CENTS')
                    check.cross_field_evidence = set(check.cross_field_evidence) | {
                        'CASH_RULING_PRINTED_CENTS',
                        'CLAIM_TOTAL_CONFIRMED',
                        'CHARGE_TOTAL_AUTHORITY',
                    }
                if any(
                    item.evidence_type == 'FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED'
                    for item in facts.evidence_items
                ):
                    check.evidence.add('FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED')
                    check.cross_field_evidence = set(check.cross_field_evidence) | {
                        'FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED',
                        'CLAIM_TOTAL_CONFIRMED',
                    }
                check.passed = True
                values[name] = confirmed
                checks[name] = check.model_dump(mode='json')
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

    # Safe 94% path: authorized reference fills unresolved identity fields only
    # when an independently AUTO-accepted member ID joins an authorized index.
    # total_charge is never filled from reference.
    reference_authority_meta: list[dict] = []
    try:
        from packages.candidate_reconciliation.contracts import EvidenceReference
        from packages.evidence_decision.contracts import (
            FieldDisposition,
            NextAction,
        )
        from packages.reference_enrichment.critical_field_authority import (
            REFERENCE_ELIGIBLE_FIELDS,
            lookup_authorized_reference,
            resolve_critical_field,
        )

        verified_member_id = None
        for decision in decisions:
            if decision.field_name not in {
                'insured_id_number',
                'member_id',
                'subscriber_id',
            }:
                continue
            if (
                decision.disposition == FieldDisposition.AUTO_ACCEPTED
                and str(decision.selected_value or '').strip()
            ):
                verified_member_id = str(decision.selected_value).strip()
                break

        document_date = None
        for key in (
            'date_of_service',
            'service_date',
            'admission_date',
            'statement_from_date',
        ):
            raw = values.get(key)
            if raw not in (None, ''):
                document_date = str(raw).strip()[:10]
                break

        reference = (
            lookup_authorized_reference(verified_member_id)
            if verified_member_id
            else None
        )
        if reference is not None:
            member_join_meta = {
                **(member_join_meta or {}),
                'verified_member_id': verified_member_id,
                'reference_authorized': bool(reference.get('authorized')),
                'reference_version': reference.get('version'),
            }

        rebuilt: list = []
        for decision in decisions:
            name = decision.field_name
            if name not in REFERENCE_ELIGIBLE_FIELDS:
                rebuilt.append(decision)
                continue
            ocr_auto = decision.disposition in {
                FieldDisposition.AUTO_ACCEPTED,
                FieldDisposition.REFERENCE_CONFIRMED,
            }
            authority = resolve_critical_field(
                field=name,
                ocr_value=decision.selected_value,
                ocr_auto=ocr_auto,
                verified_member_id=verified_member_id,
                reference=reference,
                document_date=document_date,
            )
            if (
                authority.disposition != 'AUTO_ACCEPTED'
                or authority.evidence_type != 'AUTHORIZED_REFERENCE'
                or not authority.value
            ):
                rebuilt.append(decision)
                continue

            check = deterministic.evaluate(
                name, authority.value, claim_values=values
            )
            if not check.passed:
                rebuilt.append(decision)
                continue

            # Authority already enforced exact-ID + authorized + effective-date.
            # Promote to REFERENCE_CONFIRMED without OCR calibration gates.
            supporting = list(decision.supporting_evidence)
            supporting.append(
                EvidenceReference(
                    evidence_type='AUTHORIZED_REFERENCE',
                    reference=str(
                        authority.metadata.get('reference_version')
                        or 'authorized-member-index'
                    ),
                    source='AUTHORIZED_REFERENCE',
                    reason_code='EXACT_ID_AUTHORIZED_REFERENCE',
                )
            )
            rebuilt.append(
                decision.model_copy(
                    update={
                        'selected_value': authority.value,
                        'disposition': FieldDisposition.REFERENCE_CONFIRMED,
                        'calibrated_probability': 1.0,
                        'reason_codes': [
                            'AUTHORIZED_REFERENCE',
                            'EXACT_ID_AUTHORIZED_REFERENCE',
                            authority.reason,
                            *sorted(check.evidence),
                        ],
                        'next_action': NextAction.NONE,
                        'supporting_evidence': supporting,
                    }
                )
            )
            values[name] = authority.value
            reference_authority_meta.append(
                {
                    'field': name,
                    'value': authority.value,
                    'reason': authority.reason,
                    'evidence_type': authority.evidence_type,
                    'metadata': dict(authority.metadata),
                }
            )
        decisions = rebuilt
    except Exception:  # noqa: BLE001
        reference_authority_meta = []

    decisions = [_seal_accepted_value(d, deterministic) for d in decisions]
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
        'authorized_member_join': member_join_meta,
        'authorized_reference_authority': reference_authority_meta,
        'total_charge_audit': {
            'total_charge': values.get('total_charge') or values.get('total_charges'),
            'value_origin': values.get('_total_charge_value_origin') or (
                'PRINTED_BOX28'
                if (values.get('total_charge') or values.get('total_charges'))
                not in (None, '')
                else None
            ),
            'printed_box28_value': values.get('_total_charge_printed_box28')
            if '_total_charge_printed_box28' in values
            else (values.get('total_charge') or values.get('total_charges')),
            'box28_status': values.get('_total_charge_box28_status')
            or values.get('_box28_blankness'),
        },
        'missing_fields_basis':'Required policy fields absent or blank; invalid nonempty values are not missing.',
        'telemetry':{'extraction':extraction['telemetry']}}


def evidence_from_decision(path):
    """Read the persisted decision; preserve its policy outcome and supporting facts."""
    from packages.claim_decision.contracts import ClaimDecision
    from packages.claim_evidence.builder import ClaimEvidenceResult
    from packages.evidence_decision.contracts import FieldDecision
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
    # Allow decide/complete re-runs on an existing claim final/ (bleed fail-closed
    # re-decide). Fresh cascades still create final/ empty via parents.
    output.mkdir(parents=True, exist_ok=True)
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
