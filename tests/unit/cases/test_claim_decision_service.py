from packages.claim_decision import (
    ClaimDecisionContext,
    ClaimDecisionService,
    ClaimDisposition,
)
from packages.evidence.models import EvidenceClass, EvidenceItem, FieldEvidenceBundle
from packages.evidence_decision import FieldDecision, FieldDisposition, NextAction


def _decision(service, family, field_name, disposition=FieldDisposition.AUTO_ACCEPTED):
    policy = service.field_policy.for_field(family, field_name)
    return FieldDecision(
        field_name=field_name,
        selected_value="VALUE",
        disposition=disposition,
        calibrated_probability=.99,
        next_action=(
            NextAction.NONE if disposition is FieldDisposition.AUTO_ACCEPTED
            else NextAction.HUMAN_REVIEW
        ),
        policy_version="evidence-policy-v2-candidate",
        criticality=policy.criticality,
        required=policy.required,
        blocks_stp=policy.blocks_stp,
        requires_review_when_unresolved=policy.requires_review_when_unresolved,
        evidence_bundle=FieldEvidenceBundle(
            field_name=field_name,
            policy_id=f"{family}:{field_name}",
            policy_version="evidence-policy-v2-candidate",
        ),
    )


def _context(service, family="CMS1500"):
    return ClaimDecisionContext(
        claim_id="claim-1",
        document_family=family,
        field_decisions=[
            _decision(service, family, name)
            for name in service.field_policy.required_fields(family)
        ],
        policy_id=service.policy_id,
        policy_version=service.policy_version,
    )


def test_all_explicit_blockers_safely_resolved_is_stp_safe():
    service = ClaimDecisionService.load()
    decision = service.decide(_context(service))
    assert decision.disposition is ClaimDisposition.STP_SAFE
    assert decision.stp_eligible


def test_one_isolated_blocker_requires_field_review():
    service = ClaimDecisionService.load()
    context = _context(service)
    context.field_decisions[0].disposition = FieldDisposition.HUMAN_REVIEW_REQUIRED
    context.field_decisions[0].next_action = NextAction.HUMAN_REVIEW
    decision = service.decide(context)
    assert decision.disposition is ClaimDisposition.FIELD_REVIEW_REQUIRED
    assert decision.blocking_unresolved_fields == [context.field_decisions[0].field_name]
    assert not decision.stp_eligible


def test_unresolved_nonblocking_field_does_not_prevent_stp():
    service = ClaimDecisionService.load()
    context = _context(service)
    context.field_decisions.append(_decision(
        service, "CMS1500", "patient_addr2",
        FieldDisposition.UNRESOLVED_NON_BLOCKING,
    ))
    decision = service.decide(context)
    assert decision.disposition is ClaimDisposition.STP_SAFE
    assert decision.nonblocking_unresolved_fields == ["patient_addr2"]


def test_claim_contradiction_requires_claim_review():
    service = ClaimDecisionService.load()
    context = _context(service)
    context.contradictions.append(EvidenceItem(
        evidence_class=EvidenceClass.E6,
        evidence_type="CLAIM_TOTAL_CONTRADICTION",
        evidence_family="claim-cross-field",
        source="test",
    ))
    decision = service.decide(context)
    assert decision.disposition is ClaimDisposition.CLAIM_REVIEW_REQUIRED
    assert decision.contradictions == ["CLAIM_TOTAL_CONTRADICTION"]


def test_charge_auto_authority_waives_stale_claim_total_contradiction():
    """AUTO total_charge with CONFIRMED must not stay HITL on stale E6 soup."""
    service = ClaimDecisionService.load()
    context = _context(service)
    context.contradictions.append(EvidenceItem(
        evidence_class=EvidenceClass.E6,
        evidence_type="CLAIM_TOTAL_CONTRADICTION",
        evidence_family="claim-cross-field",
        source="test",
    ))
    tc = next(d for d in context.field_decisions if d.field_name == "total_charge")
    tc.disposition = FieldDisposition.AUTO_ACCEPTED
    tc.reason_codes = [
        "CLAIM_TOTAL_CONFIRMED",
        "CHARGE_TOTAL_AUTHORITY",
        "CASH_RULING_PRINTED_CENTS",
    ]
    decision = service.decide(context)
    assert "CLAIM_TOTAL_CONTRADICTION" not in decision.contradictions
    assert decision.disposition in {
        ClaimDisposition.STP_SAFE,
        ClaimDisposition.STP_STANDARD,
    }
    assert decision.stp_eligible


def test_charge_di_local_confirmed_waives_stale_claim_total_contradiction():
    """AUTO Box 28 with DI+local confirmation clears failed-integrity line Σ HITL."""
    service = ClaimDecisionService.load()
    context = _context(service)
    context.contradictions.append(EvidenceItem(
        evidence_class=EvidenceClass.E6,
        evidence_type="CLAIM_TOTAL_CONTRADICTION",
        evidence_family="claim-cross-field",
        source="test",
    ))
    tc = next(d for d in context.field_decisions if d.field_name == "total_charge")
    tc.disposition = FieldDisposition.AUTO_ACCEPTED
    tc.reason_codes = [
        "HARD_VALIDATION_PASSED",
        "CHARGE_DI_LOCAL_CONFIRMED",
        "FORMAT_VALID",
    ]
    decision = service.decide(context)
    assert "CLAIM_TOTAL_CONTRADICTION" not in decision.contradictions
    assert decision.disposition in {
        ClaimDisposition.STP_SAFE,
        ClaimDisposition.STP_STANDARD,
    }
    assert decision.stp_eligible


def test_relieved_field_conflict_does_not_force_claim_review():
    """AUTO_ACCEPTED fields may retain OCR alternatives; claim STP must proceed."""
    from packages.candidate_reconciliation.contracts import EvidenceReference

    service = ClaimDecisionService.load()
    context = _context(service)
    dob = next(d for d in context.field_decisions if d.field_name == "patient_dob")
    dob.conflicting_evidence = [
        EvidenceReference(
            evidence_type="OCR_CANDIDATE",
            reference="alt",
            source="rapidocr",
            reason_code="CONFLICTING_VALUE:junk",
        )
    ]
    decision = service.decide(context)
    assert decision.disposition in {
        ClaimDisposition.STP_SAFE,
        ClaimDisposition.STP_STANDARD,
    }
    assert "FIELD_CONFLICT:patient_dob" not in decision.contradictions
    assert decision.stp_eligible


def test_unresolved_field_conflict_still_forces_claim_review():
    from packages.candidate_reconciliation.contracts import EvidenceReference

    service = ClaimDecisionService.load()
    context = _context(service)
    dob = next(d for d in context.field_decisions if d.field_name == "patient_dob")
    dob.disposition = FieldDisposition.HUMAN_REVIEW_REQUIRED
    dob.next_action = NextAction.HUMAN_REVIEW
    dob.conflicting_evidence = [
        EvidenceReference(
            evidence_type="OCR_CANDIDATE",
            reference="alt",
            source="rapidocr",
            reason_code="CONFLICTING_VALUE:other",
        )
    ]
    decision = service.decide(context)
    assert decision.disposition is ClaimDisposition.CLAIM_REVIEW_REQUIRED
    assert "FIELD_CONFLICT:patient_dob" in decision.contradictions


def test_missing_required_decisions_fail_closed_without_review_task_proxy():
    service = ClaimDecisionService.load()
    decision = service.decide(ClaimDecisionContext(
        claim_id="claim-1",
        document_family="CMS1500",
        policy_id=service.policy_id,
        policy_version=service.policy_version,
    ))
    assert decision.disposition is ClaimDisposition.FIELD_REVIEW_REQUIRED
    assert set(decision.blocking_unresolved_fields) == set(
        service.field_policy.required_fields("CMS1500")
    )


def test_invalid_document_integrity_is_rejected():
    service = ClaimDecisionService.load()
    context = _context(service)
    context.document_integrity_valid = False
    assert service.decide(context).disposition is ClaimDisposition.DOCUMENT_REJECTED


def test_identical_contexts_produce_identical_serialized_decisions():
    service = ClaimDecisionService.load()
    serialized = _context(service).model_dump(mode="json")
    runtime = service.decide(ClaimDecisionContext.model_validate(serialized))
    evaluation = service.decide(ClaimDecisionContext.model_validate(serialized))
    assert runtime.model_dump(mode="json") == evaluation.model_dump(mode="json")
