from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from itertools import combinations
from uuid import NAMESPACE_URL, uuid5

from packages.evidence.models import (
    EvidenceClass,
    EvidenceItem,
    FieldEvidenceBundle,
    StructuralLocalizationEvidence,
)
from packages.evidence.normalization import normalize_agreement_value
from packages.evidence_dependency import DependencyRelation, EvidenceDependencyService
from packages.ocr.contracts import OCRCandidate
from packages.ocr.independence import independence_group


def engine_family(engine: str) -> str:
    """Compatibility alias; family diversity is not independence proof."""
    family = independence_group(engine)
    return "CLOUD_AI_FAMILY" if family in {
        "GEMINI_FAMILY", "TEXTRACT_FAMILY", "AZURE_READ_FAMILY"
    } else family


def _ai_agrees_with_local(field_name: str, ai_value: str, local_value: str) -> bool:
    """Vision read matches a local engine under field-aware equivalence."""
    name = (field_name or "").casefold()
    if normalize_agreement_value(field_name, ai_value) == normalize_agreement_value(
        field_name, local_value
    ):
        return True
    if "name" in name:
        from packages.candidate_reconciliation.reconciler import (
            _name_tokens,
            values_conflict_equivalent,
        )

        if values_conflict_equivalent(field_name, ai_value, local_value):
            return True
        ai_toks = _name_tokens(ai_value)
        local_toks = _name_tokens(local_value)
        if len(ai_toks) >= 2 and len(local_toks) >= 2:
            if ai_toks == local_toks[-len(ai_toks) :] or local_toks == ai_toks[-len(local_toks) :]:
                return True
        return False
    if "dob" in name or name.endswith("_date") or "date" in name:
        # Normalized calendar equality is the agreement signal for DOB/date.
        return bool(
            normalize_agreement_value(field_name, ai_value)
            and normalize_agreement_value(field_name, ai_value)
            == normalize_agreement_value(field_name, local_value)
        )
    return False


def _vision_vendor_id(engine: object) -> str | None:
    text = str(engine or "").casefold()
    if "claude" in text or "anthropic" in text:
        return "claude"
    if "gpt4o" in text or "gpt-4o" in text:
        return "gpt4o"
    return None


def _charge_has_place_shift_rival(field_name: str, agreed: str, candidates: list[OCRCandidate]) -> bool:
    """True when some other candidate is a ×10/×100 or digit-drop twin."""
    from decimal import Decimal

    from packages.claim_evidence.line_sum_authority import (
        is_currency_digit_drop_twin,
        is_decimal_place_shift,
        parse_currency,
    )

    target = parse_currency(agreed)
    if target is None:
        return False
    for cand in candidates:
        raw = str(cand.value or "")
        other = parse_currency(raw)
        if other is None or other == target:
            continue
        if is_decimal_place_shift(agreed, raw) or is_currency_digit_drop_twin(agreed, raw):
            return True
        for factor in (Decimal(10), Decimal(100)):
            if abs(target * factor - other) <= Decimal("2.00"):
                return True
            if abs(other * factor - target) <= Decimal("2.00"):
                return True
            if target > 0 and other > 0:
                ratio = other / target if other > target else target / other
                if abs(ratio - factor) / factor <= Decimal("0.02"):
                    return True
    return False


def _append_di_partner_agreement(
    bundle: FieldEvidenceBundle,
    field_name: str,
    candidates: list[OCRCandidate],
) -> None:
    """Mint E2 when Document Intelligence agrees with Claude or one local.

    Names: Claude + DI may replace a single confusable local (FRANCAVLLA vs
    FRANCAVILLA). Charges: DI + Rapid, or DI + Claude, but not when another
    candidate is a cents-column or digit-drop twin (4972 vs 49.72, 13 vs 131).
    """
    name = (field_name or "").casefold()
    by_norm: dict[str, dict[str, OCRCandidate]] = {}
    for cand in candidates:
        if not (cand.value or "").strip():
            continue
        group = independence_group(cand.engine)
        norm = normalize_agreement_value(field_name, cand.value)
        if not norm:
            continue
        by_norm.setdefault(norm, {})[group] = cand

    if "name" in name:
        for norm, groups in by_norm.items():
            if "CLOUD_AI_FAMILY" not in groups or "AZURE_READ_FAMILY" not in groups:
                continue
            vision = groups["CLOUD_AI_FAMILY"]
            di = groups["AZURE_READ_FAMILY"]
            bundle.items.append(
                EvidenceItem(
                    evidence_class=EvidenceClass.E2,
                    evidence_type="OCR_AGREEMENT_INDEPENDENT",
                    evidence_family="INDEPENDENT_OCR_AGREEMENT",
                    source="evidence_builder",
                    value=str(vision.value or di.value),
                    independent=True,
                    metadata={
                        "engines": [vision.engine, di.engine],
                        "agreement_type": "NAME_DI_VISION_AGREEMENT",
                        "dependency_relation": "INDEPENDENT",
                        "normalized_value": norm,
                    },
                )
            )
            return

    if "charge" not in name:
        return
    for norm, groups in by_norm.items():
        if "AZURE_READ_FAMILY" not in groups:
            continue
        partner = groups.get("RAPIDOCR_FAMILY") or groups.get("CLOUD_AI_FAMILY")
        if partner is None:
            continue
        agreed_value = str(groups["AZURE_READ_FAMILY"].value or partner.value)
        if _charge_has_place_shift_rival(field_name, agreed_value, candidates):
            continue
        bundle.items.append(
            EvidenceItem(
                evidence_class=EvidenceClass.E2,
                evidence_type="OCR_AGREEMENT_INDEPENDENT",
                evidence_family="INDEPENDENT_OCR_AGREEMENT",
                source="evidence_builder",
                value=agreed_value,
                independent=True,
                metadata={
                    "engines": [groups["AZURE_READ_FAMILY"].engine, partner.engine],
                    "agreement_type": "CHARGE_DI_PARTNER_AGREEMENT",
                    "dependency_relation": "INDEPENDENT",
                    "normalized_value": norm,
                },
            )
        )
        return


def _append_dual_vision_agreement(
    bundle: FieldEvidenceBundle,
    field_name: str,
    candidates: list[OCRCandidate],
) -> None:
    """Mint independent E2 when Claude + gpt-4o agree on the same shaped value.

    Active rule from remasure field evidence: dual authorized vision vendors are
    independent confirmation even when local OCR is absent or correlated soup.
    """
    by_norm: dict[str, dict[str, OCRCandidate]] = {}
    for cand in candidates:
        if not (cand.value or "").strip():
            continue
        vendor = _vision_vendor_id(cand.engine)
        if vendor is None:
            continue
        norm = normalize_agreement_value(field_name, cand.value)
        if not norm:
            continue
        by_norm.setdefault(norm, {})[vendor] = cand
    for norm, vendors in by_norm.items():
        if "claude" not in vendors or "gpt4o" not in vendors:
            continue
        claude = vendors["claude"]
        gpt4o = vendors["gpt4o"]
        bundle.items.append(
            EvidenceItem(
                evidence_class=EvidenceClass.E2,
                evidence_type="OCR_AGREEMENT_INDEPENDENT",
                evidence_family="INDEPENDENT_OCR_AGREEMENT",
                source="evidence_builder",
                value=str(claude.value or gpt4o.value),
                independent=True,
                metadata={
                    "engines": ["anthropic_claude_crop", "azure_gpt4o_crop"],
                    "agreement_type": "DUAL_VISION_VENDOR_AGREEMENT",
                    "dependency_relation": "INDEPENDENT",
                    "normalized_value": norm,
                    "candidate_ids": [
                        candidate_identifier(claude),
                        candidate_identifier(gpt4o),
                    ],
                },
            )
        )
        return


def _append_ai_local_corroboration(
    bundle: FieldEvidenceBundle,
    field_name: str,
    candidates: list[OCRCandidate],
) -> None:
    """Mint E2 when a vision read agrees with a local engine and nothing strong dissents.

    GPT-4o is not a sole authority. A second local family, or one local plus a
    non-dissenting sibling, is required. Garbage single-token names stay HITL.
    """
    name = (field_name or "").casefold()
    if not any(token in name for token in ("name", "dob", "date")):
        return
    ai = [
        cand
        for cand in candidates
        if engine_family(cand.engine) == "CLOUD_AI_FAMILY" and (cand.value or "").strip()
    ]
    local = [
        cand
        for cand in candidates
        if engine_family(cand.engine) != "CLOUD_AI_FAMILY" and (cand.value or "").strip()
    ]
    if not ai or not local:
        return
    from packages.candidate_reconciliation.reconciler import _name_is_strong_person

    for vision in ai:
        agreeing = [
            cand
            for cand in local
            if _ai_agrees_with_local(field_name, str(vision.value), str(cand.value))
        ]
        if not agreeing:
            continue
        dissenting = []
        for cand in local:
            if cand in agreeing:
                continue
            if "name" in name:
                if _name_is_strong_person(str(cand.value or "")) and not _ai_agrees_with_local(
                    field_name, str(vision.value), str(cand.value)
                ):
                    dissenting.append(cand)
            else:
                other = normalize_agreement_value(field_name, cand.value)
                target = normalize_agreement_value(field_name, vision.value)
                if other and other != target:
                    dissenting.append(cand)
        if dissenting:
            continue
        families = {engine_family(cand.engine) for cand in agreeing}
        if not families:
            continue
        bundle.items.append(
            EvidenceItem(
                evidence_class=EvidenceClass.E2,
                evidence_type="OCR_AGREEMENT_INDEPENDENT",
                evidence_family="INDEPENDENT_OCR_AGREEMENT",
                source="evidence_builder",
                value=str(vision.value),
                independent=True,
                metadata={
                    "engines": sorted(families | {"CLOUD_AI_FAMILY"}),
                    "agreement_type": "AI_LOCAL_CORROBORATED",
                    "dependency_relation": "INDEPENDENT",
                    "local_engine_family_confirmation": True,
                },
            )
        )
        return


_STRONG_DETERMINISTIC_FACTS = {
    "CHECKSUM_VALID",
    "NPI_CHECKSUM_VALID",
    "CODE_REFERENCE_VALID",
    "DOB_BEFORE_SERVICE_DATE",
    "DATE_RELATIONSHIP_VALID",
    "FINANCIAL_RECONCILIATION_VALID",
    "LINE_TOTALS_RECONCILED",
    "PROVIDER_IDENTITY_REFERENCE_MATCH",
    "MULTI_ATTRIBUTE_IDENTITY_CONFIRMED",
}


def deterministic_strength(fact: str) -> str:
    return "STRONG" if fact in _STRONG_DETERMINISTIC_FACTS else "WEAK"


def candidate_identifier(candidate: OCRCandidate) -> str:
    if candidate.evidence_reference:
        return candidate.evidence_reference
    payload = (
        f"{candidate.engine}|{candidate.model_version}|{candidate.raw_value}|"
        f"{candidate.preprocessing_variant}"
    )
    return sha256(payload.encode()).hexdigest()[:24]


def build_evidence_bundle(
    *,
    field_name: str,
    candidates: list[OCRCandidate],
    registration_confidence: float | None,
    wrong_crop_suspected: bool,
    deterministic_evidence: set[str],
    hard_validation_passed: bool,
    deterministic_evidence_version: str | None = None,
    reference=None,
    cross_field_evidence: set[str] | None = None,
    structural_evidence_source: str | None = None,
    structural_localization: StructuralLocalizationEvidence | None = None,
    reference_source_state: str = "DISABLED",
    route_id: str | None = None,
    route_status: str | None = None,
    route_mode: str | None = None,
    rejected_route_ids: list[str] | None = None,
) -> FieldEvidenceBundle:
    populated = [candidate for candidate in candidates if candidate.value]
    selected = max(populated, key=lambda item: item.raw_confidence, default=None)
    candidate_ids = [candidate_identifier(candidate) for candidate in candidates]
    bundle = FieldEvidenceBundle(
        field_name=field_name,
        route_id=route_id,
        route_status=route_status,
        route_mode=route_mode,
        rejected_route_ids=rejected_route_ids or [],
        candidate_value=selected.value if selected else None,
        selected_candidate_id=candidate_identifier(selected) if selected else None,
        candidate_ids=candidate_ids,
    )
    if not populated:
        bundle.items.append(
            EvidenceItem(
                evidence_class=EvidenceClass.E0,
                evidence_type="NO_EXTRACTION_EVIDENCE",
                evidence_family="NO_EVIDENCE",
                source="pipeline",
            )
        )
    by_value: dict[str, list[OCRCandidate]] = defaultdict(list)
    for candidate in populated:
        family = engine_family(candidate.engine)
        candidate_id = candidate_identifier(candidate)
        bundle.items.append(
            EvidenceItem(
                evidence_class=EvidenceClass.E7
                if family == "CLOUD_AI_FAMILY"
                else EvidenceClass.E1,
                evidence_type="AI_EXTRACTION" if family == "CLOUD_AI_FAMILY" else "OCR_EXTRACTION",
                evidence_family=family,
                source=candidate.engine,
                value=candidate.value,
                supports_candidate_id=candidate_id,
                confidence=candidate.raw_confidence,
                independent=False,
                metadata={
                    "preprocessing_variant": candidate.preprocessing_variant,
                    "provenance": (
                        candidate.provenance.model_dump(mode="json")
                        if candidate.provenance else None
                    ),
                },
            )
        )
        normalized = normalize_agreement_value(field_name, candidate.value)
        if normalized:
            by_value[normalized].append(candidate)
    dependency_service = EvidenceDependencyService()
    relation_rank = {
        DependencyRelation.UNKNOWN: 0,
        DependencyRelation.CORRELATED: 1,
        DependencyRelation.PARTIALLY_INDEPENDENT: 2,
        DependencyRelation.INDEPENDENT: 3,
    }
    emitted_independent_e2 = False
    for value, agreeing in by_value.items():
        local = [item for item in agreeing if engine_family(item.engine) != "CLOUD_AI_FAMILY"]
        pair_results = [
            (left, right, dependency_service.classify(left.provenance, right.provenance))
            for left, right in combinations(local, 2)
            if engine_family(left.engine) != engine_family(right.engine)
        ]
        if pair_results:
            left, right, dependency = max(
                pair_results, key=lambda item: relation_rank[item[2].relation]
            )
            relation = dependency.relation
            engines = sorted({engine_family(item.engine) for item in local})
            engine_set = set(engines)
            # Cascade forces rapid confirmation behind paddle for patient_name.
            # Missing lineage → UNKNOWN; still treat paddle+rapid as independent
            # confirmation. Proven CORRELATED same-crop agreement stays blocked.
            # Tesseract pairings are unchanged (not the forced confirm path).
            local_family_confirm = (
                relation
                in {
                    DependencyRelation.UNKNOWN,
                    DependencyRelation.PARTIALLY_INDEPENDENT,
                }
                and engine_set >= {"PADDLE_FAMILY", "RAPIDOCR_FAMILY"}
            )
            independent = (
                relation == DependencyRelation.INDEPENDENT or local_family_confirm
            )
            if local_family_confirm and relation != DependencyRelation.INDEPENDENT:
                evidence_type = "OCR_AGREEMENT_INDEPENDENT"
                evidence_family = "INDEPENDENT_OCR_AGREEMENT"
            else:
                evidence_type = {
                    DependencyRelation.CORRELATED: "OCR_AGREEMENT_CORRELATED",
                    DependencyRelation.PARTIALLY_INDEPENDENT: (
                        "OCR_AGREEMENT_PARTIALLY_INDEPENDENT"
                    ),
                    DependencyRelation.INDEPENDENT: "OCR_AGREEMENT_INDEPENDENT",
                    DependencyRelation.UNKNOWN: "OCR_AGREEMENT_UNKNOWN_DEPENDENCY",
                }[relation]
                evidence_family = (
                    "INDEPENDENT_OCR_AGREEMENT"
                    if relation == DependencyRelation.INDEPENDENT
                    else f"OCR_AGREEMENT:{relation.value}"
                )
            bundle.items.append(
                EvidenceItem(
                    evidence_class=EvidenceClass.E2,
                    evidence_type=evidence_type,
                    evidence_family=evidence_family,
                    source="evidence_builder",
                    value=value,
                    independent=independent,
                    metadata={
                        "candidate_ids": [
                            candidate_identifier(left),
                            candidate_identifier(right),
                        ],
                        "engines": engines,
                        "agreement_type": "FIELD_AWARE_NORMALIZED_EXACT",
                        "dependency_relation": relation.value,
                        "dependency_reasons": list(dependency.reasons),
                        "dependency_dimensions": dependency.dependency_dimensions,
                        "dependency_confidence": dependency.confidence,
                        "local_engine_family_confirmation": local_family_confirm,
                        "dependency_matrix": [
                            {
                                "candidate_a": candidate_identifier(pair_left),
                                "candidate_b": candidate_identifier(pair_right),
                                "relation": pair_dependency.relation.value,
                                "reasons": list(pair_dependency.reasons),
                                "dimensions": pair_dependency.dependency_dimensions,
                                "confidence": pair_dependency.confidence,
                            }
                            for pair_left, pair_right, pair_dependency in pair_results
                        ],
                    },
                )
            )
            if independent and evidence_type == "OCR_AGREEMENT_INDEPENDENT":
                emitted_independent_e2 = True
    if not emitted_independent_e2:
        _append_dual_vision_agreement(bundle, field_name, populated)
        if not any(
            item.evidence_class == EvidenceClass.E2 and item.independent
            for item in bundle.items
        ):
            _append_ai_local_corroboration(bundle, field_name, populated)
        if not any(
            item.evidence_class == EvidenceClass.E2 and item.independent
            for item in bundle.items
        ):
            _append_di_partner_agreement(bundle, field_name, populated)
    if structural_localization is not None:
        if structural_localization.confirmed and not wrong_crop_suspected:
            bundle.items.append(
                EvidenceItem(
                    evidence_class=EvidenceClass.E3,
                    evidence_type=structural_localization.evidence_type.value,
                    evidence_family="STRUCTURAL_LOCALIZATION",
                    source=structural_localization.source,
                    confidence=structural_localization.confidence,
                    deterministic=True,
                    version=structural_localization.version,
                    metadata={"reason_codes": list(structural_localization.reason_codes)},
                )
            )
            bundle.items[-1].metadata.update({
                "field_name": structural_localization.field_name,
                "field_bbox": structural_localization.field_bbox,
                "localization_mode": structural_localization.localization_mode,
                "anchor_id": structural_localization.anchor_id,
                "anchor_confidence": structural_localization.anchor_confidence,
                "neighbor_evidence": list(structural_localization.neighbor_evidence),
                "positive_bounded_roi": structural_localization.positive_bounded_roi,
                "geometry_valid": structural_localization.geometry_valid,
                "registration_compatible": structural_localization.registration_compatible,
                "field_specific": bool(
                    structural_localization.field_name == field_name
                    and structural_localization.field_bbox
                    and structural_localization.positive_bounded_roi
                    and structural_localization.geometry_valid
                ),
            })
    elif (
        registration_confidence is not None
        and registration_confidence >= 0.80
        and not wrong_crop_suspected
    ):
        # Compatibility behavior for persisted pre-Phase-8.4 contexts. New
        # runtime/replay contexts must pass qualified structural evidence.
        bundle.items.append(
            EvidenceItem(
                evidence_class=EvidenceClass.E3,
                evidence_type="REGISTRATION_CONFIRMED",
                evidence_family="PAGE_GEOMETRY",
                source=structural_evidence_source or "registration",
                confidence=registration_confidence,
                deterministic=True,
                metadata={
                    "structural_source": structural_evidence_source or "MEASURED_REGISTRATION"
                },
            )
        )
    facts = set(deterministic_evidence)
    if hard_validation_passed:
        facts.add("HARD_VALIDATION_PASSED")
    for fact in sorted(facts):
        strength = deterministic_strength(fact)
        bundle.items.append(
            EvidenceItem(
                evidence_class=EvidenceClass.E4,
                evidence_type=(
                    f"STRONG_DETERMINISTIC:{fact}"
                    if strength == "STRONG"
                    else f"WEAK_PLAUSIBILITY:{fact}"
                ),
                evidence_family=f"DETERMINISTIC:{strength}:{fact}",
                source="validation",
                deterministic=True,
                version=deterministic_evidence_version,
                metadata={"validation_result": "PASS", "strength": strength, "fact": fact},
            )
        )
    if (
        reference
        and reference.verified
        and not reference.contradiction
        and reference_source_state == "AUTHORIZED"
    ):
        bundle.items.append(
            EvidenceItem(
                evidence_class=EvidenceClass.E5,
                evidence_type="REFERENCE_CONFIRMED",
                evidence_family=f"REFERENCE:{reference.source or 'unknown'}",
                source=reference.source or "reference",
                value=reference.value,
                authoritative=True,
                version=reference.version,
                metadata={
                    "matching_attributes": reference.matched_attributes,
                    "conflicts": reference.conflicts,
                },
            )
        )
    elif reference and (reference.contradiction or reference.conflicts):
        bundle.contradictions.append(
            EvidenceItem(
                evidence_class=EvidenceClass.E5,
                evidence_type="REFERENCE_CONTRADICTION",
                evidence_family=f"REFERENCE:{reference.source or 'unknown'}",
                source=reference.source or "reference",
                value=reference.value,
                authoritative=True,
                version=reference.version,
                metadata={
                    "matching_attributes": reference.matched_attributes,
                    "conflicts": reference.conflicts,
                },
            )
        )
    for fact in sorted(cross_field_evidence or set()):
        bundle.items.append(
            EvidenceItem(
                evidence_class=EvidenceClass.E6,
                evidence_type=fact,
                evidence_family=f"CROSS_FIELD:{fact}",
                source="claim_reconciliation",
                deterministic=True,
            )
        )
    for index, item in enumerate([*bundle.items, *bundle.contradictions]):
        item.evidence_id = uuid5(
            NAMESPACE_URL,
            "|".join(
                (
                    field_name,
                    str(index),
                    item.evidence_class.value,
                    item.evidence_type,
                    item.evidence_family,
                    item.source,
                    item.value or "",
                    item.supports_candidate_id or "",
                    item.version or "",
                )
            ),
        )
    return bundle
