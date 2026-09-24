from __future__ import annotations

from pathlib import Path

import yaml

from packages.claim_decision.contracts import (
    ClaimDecision,
    ClaimDecisionContext,
    ClaimDisposition,
)
from packages.criticality import CriticalityLevel
from packages.evidence_decision import FieldDecision, FieldDisposition, NextAction
from packages.field_policy import FieldPolicyRegistry
from packages.product_gates.accuracy_accept_policy import evaluate_critical_accept

DEFAULT_CLAIM_POLICY_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "claim_decision_policies.yaml"
)

_ACCEPTED = {
    FieldDisposition.AUTO_ACCEPTED,
    FieldDisposition.REFERENCE_CONFIRMED,
    FieldDisposition.HUMAN_CONFIRMED,
}


class ClaimDecisionService:
    """Sole authority for claim STP, field review, claim review, and rejection."""

    def __init__(
        self,
        config: dict,
        field_policy: FieldPolicyRegistry | None = None,
        configuration_identity: dict[str, str] | None = None,
    ) -> None:
        self.config = config
        self.policy_id = str(config["policy_id"])
        self.policy_version = str(config["version"])
        self.field_policy = field_policy or FieldPolicyRegistry.load()
        self.configuration_identity = configuration_identity or {
            "runtime_profile_id": "UNBOUND",
            "claim_policy_hash": "UNBOUND",
        }

    @classmethod
    def load(
        cls,
        path: str | Path = DEFAULT_CLAIM_POLICY_PATH,
        field_policy: FieldPolicyRegistry | None = None,
        configuration_identity: dict[str, str] | None = None,
    ) -> ClaimDecisionService:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(
            payload,
            field_policy=field_policy,
            configuration_identity=configuration_identity,
        )

    def decide(self, context: ClaimDecisionContext) -> ClaimDecision:
        if context.policy_id != self.policy_id:
            return self._result(
                context,
                ClaimDisposition.CLAIM_REVIEW_REQUIRED,
                reasons=["CLAIM_POLICY_ID_MISMATCH"],
            )
        if context.policy_version not in {None, self.policy_version}:
            return self._result(
                context,
                ClaimDisposition.CLAIM_REVIEW_REQUIRED,
                reasons=["CLAIM_POLICY_VERSION_MISMATCH"],
            )

        invalid_integrity = [
            reason
            for valid, reason in (
                (context.document_integrity_valid, "DOCUMENT_INTEGRITY_FAILED"),
                (context.template_integrity_valid, "TEMPLATE_INTEGRITY_FAILED"),
                (context.registration_integrity_valid, "REGISTRATION_INTEGRITY_FAILED"),
                (context.process_integrity_valid, "PROCESS_INTEGRITY_FAILED"),
            )
            if not valid
        ]
        if invalid_integrity:
            return self._result(
                context,
                ClaimDisposition.DOCUMENT_REJECTED,
                reasons=invalid_integrity,
            )

        present_fields = {
            self.field_policy.canonical_name(context.document_family, decision.field_name)
            for decision in context.field_decisions
        }
        missing_required = (
            [
                name
                for name in self.field_policy.required_fields(context.document_family)
                if name not in present_fields
            ]
            if context.enforce_configured_required_fields
            else []
        )
        if missing_required:
            return self._result(
                context,
                ClaimDisposition.FIELD_REVIEW_REQUIRED,
                extra_blocking=missing_required,
                reasons=["REQUIRED_FIELD_DECISIONS_MISSING"],
            )

        # Resolve Box-4 SAME / patient-twin insured_name before accept-policy
        # demotion. Unresolved SAME was demoted to HITL even when patient_name
        # was already AUTO — the dominant false STP loss on Hackathon-5000.
        context = self._resolve_insured_name_patient_twin(context)
        # Product FA=0: demote AUTO that fail accept policy before STP calc.
        context = self._apply_product_accuracy_policy(context)

        blocking: list[FieldDecision] = []
        nonblocking: list[FieldDecision] = []
        for decision in context.field_decisions:
            if decision.disposition in _ACCEPTED:
                continue
            blocks_stp = decision.blocks_stp
            if blocks_stp is None:
                blocks_stp = self.field_policy.for_field(
                    context.document_family,
                    decision.field_name,
                ).blocks_stp
            (blocking if blocks_stp else nonblocking).append(decision)

        contradictions = self._contradictions(context)
        if contradictions:
            return self._result(
                context,
                ClaimDisposition.CLAIM_REVIEW_REQUIRED,
                blocking=blocking,
                nonblocking=nonblocking,
                contradictions=contradictions,
                reasons=["UNRESOLVED_CLAIM_CONTRADICTION"],
            )

        coordinated = self._coordinated_blockers(context, blocking)
        if not context.structural_consistency_valid or coordinated:
            reasons = []
            if not context.structural_consistency_valid:
                reasons.append("CLAIM_STRUCTURE_INCONSISTENT")
            if coordinated:
                reasons.append("DEPENDENT_FIELD_GROUP_UNRESOLVED")
            return self._result(
                context,
                ClaimDisposition.CLAIM_REVIEW_REQUIRED,
                blocking=blocking,
                nonblocking=nonblocking,
                reasons=reasons,
            )

        if blocking:
            return self._result(
                context,
                ClaimDisposition.FIELD_REVIEW_REQUIRED,
                blocking=blocking,
                nonblocking=nonblocking,
                reasons=["BLOCKING_FIELDS_UNRESOLVED"],
            )

        safe = self._qualifies_safe(context)
        return self._result(
            context,
            ClaimDisposition.STP_SAFE if safe else ClaimDisposition.STP_STANDARD,
            nonblocking=nonblocking,
            reasons=[
                "ALL_BLOCKING_FIELDS_SAFELY_RESOLVED"
                if safe
                else "ALL_BLOCKING_FIELDS_RESOLVED_STANDARD"
            ],
        )

    @staticmethod
    def _soft_person_name_twin(left: str, right: str) -> bool:
        """True when two displays are the same person under OCR confusables."""
        from packages.candidate_reconciliation.reconciler import (
            _canonical_person_name,
            _names_differ_by_confusable_edit,
            _names_differ_by_confusable_insertion,
            _names_differ_by_confusable_substitution,
            _names_differ_by_optional_middle_initial,
            _names_differ_by_token_order,
            _names_differ_by_tokenwise_confusable,
        )

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

    @classmethod
    def _resolve_insured_name_patient_twin(
        cls,
        context: ClaimDecisionContext,
    ) -> ClaimDecisionContext:
        """Promote insured_name when it is SAME or a twin of AUTO patient_name.

        Precision-safe: never copies Box 2 onto a different strong Box 4 person
        (spouse/child). Only Self / unknown relationship.
        """
        from packages.candidate_reconciliation.reconciler import (
            _name_is_self_reference,
            _name_is_short_fragment,
            _name_is_strong_person,
        )
        from packages.geometry_authority.form_redundancy import relationship_is_self

        by_name = {d.field_name: d for d in context.field_decisions}
        patient = by_name.get("patient_name")
        insured = by_name.get("insured_name")
        if patient is None or insured is None:
            return context
        if patient.disposition not in _ACCEPTED:
            return context
        pval = str(patient.selected_value or "").strip()
        if not pval or not _name_is_strong_person(pval):
            return context

        rel = None
        for key in ("insured_relationship", "relationship", "rel_code"):
            other = by_name.get(key)
            if other is not None and str(other.selected_value or "").strip():
                rel = other.selected_value
                break
        if not (relationship_is_self(rel) or not str(rel or "").strip()):
            return context

        ival = str(insured.selected_value or "").strip()
        already_auto = insured.disposition in _ACCEPTED
        is_same = bool(ival) and _name_is_self_reference(ival)
        is_twin = bool(ival) and cls._soft_person_name_twin(pval, ival)
        is_weak = (not ival) or _name_is_short_fragment(ival) or (
            len(ival) <= 4 and not _name_is_strong_person(ival)
        )

        if already_auto and not is_same:
            return context
        if not (is_same or is_twin or is_weak):
            return context

        reason = (
            "INSURED_NAME_SAME_RESOLVED_TO_PATIENT"
            if is_same
            else "INSURED_NAME_PATIENT_TWIN_MATCH"
            if is_twin
            else "INSURED_NAME_PATIENT_TWIN_PROMOTED"
        )
        rewritten: list[FieldDecision] = []
        for decision in context.field_decisions:
            if decision.field_name != "insured_name":
                rewritten.append(decision)
                continue
            rewritten.append(
                decision.model_copy(
                    update={
                        "selected_value": pval,
                        "disposition": FieldDisposition.AUTO_ACCEPTED,
                        "conflicting_evidence": [],
                        "reason_codes": list(
                            dict.fromkeys(
                                [
                                    *list(decision.reason_codes or []),
                                    "HARD_VALIDATION_PASSED",
                                    reason,
                                ]
                            )
                        ),
                        "next_action": NextAction.NONE,
                        "blocks_stp": False,
                    }
                )
            )
        return context.model_copy(update={"field_decisions": rewritten})

    @staticmethod
    def _apply_product_accuracy_policy(
        context: ClaimDecisionContext,
    ) -> ClaimDecisionContext:
        """Fail-closed: placeholder / form-junk AUTO → HUMAN_REVIEW (HITL)."""
        patient_name = next(
            (
                d.selected_value
                for d in context.field_decisions
                if d.field_name == "patient_name"
                and d.disposition in _ACCEPTED
                and d.selected_value
            ),
            None,
        )
        rewritten: list[FieldDecision] = []
        changed = False
        for decision in context.field_decisions:
            if decision.disposition not in _ACCEPTED:
                rewritten.append(decision)
                continue
            verdict = evaluate_critical_accept(
                decision.field_name,
                decision.selected_value,
                patient_name=patient_name,
            )
            if verdict.allow_auto:
                rewritten.append(decision)
                continue
            changed = True
            rewritten.append(
                decision.model_copy(
                    update={
                        "disposition": FieldDisposition.HUMAN_REVIEW_REQUIRED,
                        "next_action": NextAction.HUMAN_REVIEW,
                        "reason_codes": list(
                            dict.fromkeys(
                                [
                                    *list(decision.reason_codes or []),
                                    "PRODUCT_ACCURACY_ACCEPT_POLICY",
                                    *list(verdict.reason_codes),
                                ]
                            )
                        ),
                        "blocks_stp": True,
                    }
                )
            )
        if not changed:
            return context
        return context.model_copy(update={"field_decisions": rewritten})

    def _qualifies_safe(self, context: ClaimDecisionContext) -> bool:
        critical_blocking: list[FieldDecision] = []
        for decision in context.field_decisions:
            policy = self.field_policy.for_field(
                context.document_family,
                decision.field_name,
            )
            level = decision.criticality or policy.criticality
            blocks = policy.blocks_stp if decision.blocks_stp is None else decision.blocks_stp
            if blocks and level in {CriticalityLevel.C2, CriticalityLevel.C3}:
                critical_blocking.append(decision)
        if not critical_blocking:
            return False
        return all(
            decision.disposition in _ACCEPTED
            and decision.evidence_bundle is not None
            and not decision.evidence_bundle.contradictions
            and not decision.evidence_bundle.missing_evidence_classes
            for decision in critical_blocking
        )

    @staticmethod
    def _coordinated_blockers(
        context: ClaimDecisionContext,
        blocking: list[FieldDecision],
    ) -> bool:
        blocked = {decision.field_name for decision in blocking}
        return any(len(blocked.intersection(group)) > 1 for group in context.dependent_field_groups)

    @staticmethod
    def _contradictions(context: ClaimDecisionContext) -> list[str]:
        descriptions = [item.evidence_type for item in context.contradictions]
        # When a field is AUTO with locked FVA authority, stale claim-level
        # soup must not re-litigate that field (esp. CLAIM_TOTAL_CONTRADICTION
        # after ChargeTotalAuthority / Box28-over-bleed / DI+local confirm).
        try:
            from packages.extraction_recovery.cloud_stop_ladder import (
                FIELD_AUTHORITY_CODES,
                field_has_authority,
            )
        except Exception:  # noqa: BLE001
            FIELD_AUTHORITY_CODES = frozenset(
                {
                    "CLAIM_TOTAL_CONFIRMED",
                    "CHARGE_TOTAL_AUTHORITY",
                    "CASH_RULING_PRINTED_CENTS",
                    "CHARGE_DI_LOCAL_CONFIRMED",
                    "CHARGE_VISION_LOCAL_CONFIRMED",
                }
            )

            def field_has_authority(reason_codes):  # type: ignore[misc]
                return bool(set(reason_codes or []) & FIELD_AUTHORITY_CODES)

        charge_auto_authority = any(
            decision.field_name in {"total_charge", "total_charges"}
            and decision.disposition in _ACCEPTED
            and field_has_authority(decision.reason_codes)
            for decision in context.field_decisions
        )
        if charge_auto_authority:
            descriptions = [
                item for item in descriptions if item != "CLAIM_TOTAL_CONTRADICTION"
            ]
        # Strip field-prefixed claim contradictions for AUTO+authority fields.
        authority_fields = {
            decision.field_name
            for decision in context.field_decisions
            if decision.disposition in _ACCEPTED
            and field_has_authority(decision.reason_codes)
        }
        if authority_fields:
            descriptions = [
                item
                for item in descriptions
                if not any(
                    item.startswith(f"{field}:") for field in authority_fields
                )
            ]
        for decision in context.field_decisions:
            # Accepted fields may still list OCR alternatives as conflicting_evidence
            # (fragments / separator twins / name confusables). Reconciler already
            # resolved those — they must not force claim-level HITL.
            if decision.conflicting_evidence and decision.disposition not in _ACCEPTED:
                descriptions.append(f"FIELD_CONFLICT:{decision.field_name}")
            if decision.evidence_bundle and decision.evidence_bundle.contradictions:
                if decision.disposition in _ACCEPTED:
                    continue
                # AUTO was already handled; non-accepted with authority still
                # should not re-open via bundle soup when FVA locked the value.
                if field_has_authority(decision.reason_codes):
                    continue
                descriptions.extend(
                    f"{decision.field_name}:{item.evidence_type}"
                    for item in decision.evidence_bundle.contradictions
                )
        return list(dict.fromkeys(descriptions))

    def _result(
        self,
        context: ClaimDecisionContext,
        disposition: ClaimDisposition,
        *,
        blocking: list[FieldDecision] | None = None,
        nonblocking: list[FieldDecision] | None = None,
        contradictions: list[str] | None = None,
        extra_blocking: list[str] | None = None,
        reasons: list[str],
    ) -> ClaimDecision:
        blocking = blocking or []
        nonblocking = nonblocking or []
        extra_blocking = extra_blocking or []
        critical = []
        for decision in blocking:
            policy = self.field_policy.for_field(
                context.document_family,
                decision.field_name,
            )
            if (decision.criticality or policy.criticality) in {
                CriticalityLevel.C2,
                CriticalityLevel.C3,
            }:
                critical.append(decision.field_name)
        for field_name in extra_blocking:
            if self.field_policy.for_field(
                context.document_family,
                field_name,
            ).criticality in {CriticalityLevel.C2, CriticalityLevel.C3}:
                critical.append(field_name)
        return ClaimDecision(
            claim_id=context.claim_id,
            disposition=disposition,
            blocking_unresolved_fields=[
                *[item.field_name for item in blocking],
                *extra_blocking,
            ],
            nonblocking_unresolved_fields=[item.field_name for item in nonblocking],
            critical_blockers=critical,
            contradictions=contradictions or [],
            reason_codes=list(dict.fromkeys(reasons)),
            stp_eligible=disposition
            in {
                ClaimDisposition.STP_SAFE,
                ClaimDisposition.STP_STANDARD,
            },
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            runtime_profile_id=self.configuration_identity["runtime_profile_id"],
            claim_policy_hash=self.configuration_identity["claim_policy_hash"],
        )
