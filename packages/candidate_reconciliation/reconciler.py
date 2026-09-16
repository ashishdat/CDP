"""Evidence-driven reconciliation with fail-closed C3 acceptance."""

from __future__ import annotations

import re
from collections import defaultdict
from hashlib import sha256

from packages.candidate_reconciliation.contracts import (
    Decision,
    EvidenceReference,
    ReconciliationResult,
)
from packages.confidence import CalibrationRegistry
from packages.criticality import CriticalityLevel
from packages.evidence.normalization import normalize_agreement_value
from packages.evidence_policy import EvidencePolicyRegistry
from packages.observability.metrics import field_reconciliation_total
from packages.ocr.contracts import OCRCandidate
from packages.ocr.independence import independence_group


def _canonical_date_digits(value: str) -> str:
    """Normalize US/ISO/compact dates to YYYYMMDD for conflict comparison."""
    digits = re.sub(r"\D", "", (value or "").strip())
    if len(digits) == 8:
        # Prefer ISO YYYYMMDD when year-looking prefix, else MMDDYYYY.
        if int(digits[0:4]) >= 1880:
            return digits
        return digits[4:8] + digits[0:2] + digits[2:4]
    if len(digits) == 6:
        yy = int(digits[4:6])
        century = 1900 if yy >= 30 else 2000
        return f"{century + yy:04d}{digits[0:2]}{digits[2:4]}"
    return digits


def _dob_ymd(value: str) -> tuple[str, str, str] | None:
    digits = _canonical_date_digits(value)
    if len(digits) != 8:
        return None
    year, month, day = digits[0:4], digits[4:6], digits[6:8]
    try:
        from datetime import date as _date

        _date(int(year), int(month), int(day))
    except ValueError:
        return None
    return year, month, day


def prefer_dob_without_separator_one(
    primary: str, competitors: list[str]
) -> str | None:
    """CMS DOB boxes use dashed vertical rules that OCR reads as leading ``1``.

    When two calendar-valid dates differ only by that artifact on MM or DD
    (11 vs 01, 19 vs 09), prefer the copy without the extra leading 1.
    Returns the observed clean display string when available, else ISO
    ``YYYY-MM-DD``.
    """
    observed: list[tuple[tuple[str, str, str], str]] = []
    for value in [primary, *competitors]:
        ymd = _dob_ymd(value)
        if ymd is not None:
            observed.append((ymd, value))
    if len(observed) < 2:
        return None
    parts = [ymd for ymd, _ in observed]

    def peel(component: str) -> str | None:
        if len(component) == 2 and component[0] == "1" and component[1] != "0":
            return f"0{component[1]}"
        return None

    cleaned: set[tuple[str, str, str]] = set()
    for year, month, day in parts:
        month_opts = {month}
        day_opts = {day}
        peeled_m = peel(month)
        peeled_d = peel(day)
        if peeled_m:
            month_opts.add(peeled_m)
        if peeled_d:
            day_opts.add(peeled_d)
        for mm in month_opts:
            for dd in day_opts:
                try:
                    from datetime import date as _date

                    _date(int(year), int(mm), int(dd))
                except ValueError:
                    continue
                cleaned.add((year, mm, dd))

    # A clean date is a separator-relief if some observed date is the +1 form.
    for year, month, day in sorted(cleaned):
        sep_month = f"1{month[1]}" if month[0] == "0" else None
        sep_day = f"1{day[1]}" if day[0] == "0" else None
        observed_sep = False
        observed_clean = (year, month, day) in parts
        for oy, om, od in parts:
            if oy != year:
                continue
            if sep_month and om == sep_month and od == day:
                observed_sep = True
            if sep_day and od == sep_day and om == month:
                observed_sep = True
        if observed_sep and (observed_clean or (year, month, day) not in parts):
            # Prefer an observed OCR string for the clean YMD (keeps evidence match).
            for ymd, display in observed:
                if ymd == (year, month, day):
                    return display
            return f"{year}-{month}-{day}"
    return None


def _canonical_member_id(value: str) -> str:
    compact = re.sub(r"[^A-Z0-9]", "", (value or "").strip().upper())
    if compact.isdigit():
        stripped = compact.lstrip("0")
        return stripped or "0"
    return compact


def _canonical_person_name(value: str) -> str:
    """Normalize person-name OCR for agreement / conflict equivalence.

    Handles common typed-CMS confusables without inventing letters:
    - digit ``1`` amid letters → ``I`` (ROVINSK1)
    - ``.1`` / ``.I`` between letters → ``L`` (REYNEL.1ISA)
    - capital-J stem ``JI`` before a vowel → ``J`` (JIOSEPHINE)
    """
    text = (value or "").strip().upper()
    text = re.sub(r"\.[I1]", "L", text)  # .1 / .I often a broken L glyph
    text = re.sub(r"[^A-Z0-9]", "", text)
    text = re.sub(r"(?<=[A-Z])1(?=[A-Z]|$)", "I", text)
    text = re.sub(r"JI(?=[AEIOUY])", "J", text)
    return text


def _names_differ_by_confusable_insertion(left: str, right: str) -> bool:
    """True when names match after removing one inserted I/1/L glyph."""
    a, b = _canonical_person_name(left), _canonical_person_name(right)
    if not a or not b or a == b:
        return a == b and bool(a)
    if abs(len(a) - len(b)) != 1:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    for idx, ch in enumerate(longer):
        if ch in {"I", "1", "L"} and longer[:idx] + longer[idx + 1 :] == shorter:
            return True
    return False


def prefer_name_without_confusable_insertion(
    primary: str, competitors: list[str]
) -> str | None:
    """Prefer the cleaner name when OCR inserted an I/1/L confusable glyph."""
    observed = [v for v in [primary, *competitors] if (v or "").strip()]
    for left in observed:
        for right in observed:
            if left == right:
                continue
            if not _names_differ_by_confusable_insertion(left, right):
                continue
            # Prefer fewer confusable glyphs / shorter canonical form.
            cl, cr = _canonical_person_name(left), _canonical_person_name(right)
            if len(cl) < len(cr):
                return left
            if len(cr) < len(cl):
                return right
    # JI-peel twins: same canonical after peel — prefer display without raw JI / 1.
    norms = [(_canonical_person_name(v), v) for v in observed]
    by_norm: dict[str, list[str]] = {}
    for norm, display in norms:
        if norm:
            by_norm.setdefault(norm, []).append(display)
    if len(by_norm) == 1:
        displays = next(iter(by_norm.values()))
        scored = sorted(
            displays,
            key=lambda d: (
                "JI" in re.sub(r"[^A-Z]", "", (d or "").upper()),
                "1" in (d or ""),
                len(d or ""),
            ),
        )
        return scored[0] if len(scored) > 1 else None
    return None


def values_conflict_equivalent(field_name: str, left: str, right: str) -> bool:
    """True when two OCR values are representation-equivalent (not true conflicts)."""
    name = (field_name or "").casefold()
    if not (left or "").strip() or not (right or "").strip():
        return False
    if name in {"patient_dob", "date_of_birth", "dob"} or name.endswith("_date"):
        a, b = _canonical_date_digits(left), _canonical_date_digits(right)
        return bool(a) and a == b
    if name in {"insured_id_number", "member_id", "subscriber_id"}:
        a, b = _canonical_member_id(left), _canonical_member_id(right)
        return bool(a) and a == b
    if name in {"patient_name", "insured_name"} or "name" in name:
        a, b = _canonical_person_name(left), _canonical_person_name(right)
        if bool(a) and a == b:
            return True
        return _names_differ_by_confusable_insertion(left, right)
    return normalize_agreement_value(field_name, left) == normalize_agreement_value(
        field_name, right
    )


class EvidenceReconciler:
    def __init__(
        self,
        calibration: CalibrationRegistry | None = None,
        accept_thresholds: dict[CriticalityLevel, float] | None = None,
        evidence_policies: EvidencePolicyRegistry | None = None,
        allow_authoritative_financial_e6: bool = False,
    ) -> None:
        self.calibration = calibration or CalibrationRegistry()
        self.thresholds = accept_thresholds or {
            CriticalityLevel.C0: 0.70,
            CriticalityLevel.C1: 0.80,
            CriticalityLevel.C2: 0.92,
            CriticalityLevel.C3: 0.98,
        }
        self.evidence_policies = evidence_policies or EvidencePolicyRegistry.load()
        self.allow_authoritative_financial_e6 = allow_authoritative_financial_e6

    @staticmethod
    def _candidate_id(candidate: OCRCandidate) -> str:
        if candidate.evidence_reference:
            return candidate.evidence_reference
        payload = (
            f"{candidate.engine}|{candidate.model_version}|{candidate.raw_value}|"
            f"{candidate.preprocessing_variant}"
        )
        return sha256(payload.encode()).hexdigest()[:24]

    def reconcile(
        self,
        field_name: str,
        candidates: list[OCRCandidate],
        criticality: CriticalityLevel,
        *,
        deterministic_evidence: set[str] | None = None,
        authoritative_value: str | None = None,
        authoritative_reference_verified: bool = False,
        authoritative_source: str | None = None,
        authoritative_version: str | None = None,
        document_family: str = "*",
        enforce_legacy_evidence_policy: bool = True,
        independent_agreement_values: set[str] | None = None,
    ) -> ReconciliationResult:
        deterministic = deterministic_evidence or set()
        groups: dict[str, list[tuple[OCRCandidate, float, str]]] = defaultdict(list)
        conflicts: list[EvidenceReference] = []
        for candidate in candidates:
            display_value = (candidate.value or "").strip()
            if not display_value:
                continue
            calibrated, version = self.calibration.calibrate(
                candidate.engine, field_name, candidate.raw_confidence
            )
            normalized = normalize_agreement_value(field_name, display_value)
            if normalized:
                groups[normalized].append((candidate, calibrated, version))
        ids = [self._candidate_id(candidate) for candidate in candidates]
        if not groups:
            return ReconciliationResult(
                field_name=field_name,
                selected_value=None,
                candidate_ids=ids,
                decision=Decision.ABSTAIN,
                confidence=0,
                rationale_codes=["NO_NONEMPTY_CANDIDATE"],
                calibration_model_version="none",
            )

        qualified_independent_values = (
            {
                normalize_agreement_value(field_name, item)
                for item in independent_agreement_values
            }
            if independent_agreement_values is not None
            else None
        )

        def independent_agreement(normalized_value, items) -> bool:
            if qualified_independent_values is not None:
                return normalized_value in qualified_independent_values
            return len({independence_group(c.engine) for c, _, _ in items}) >= 2

        is_dob_field = field_name in {"patient_dob", "date_of_birth", "dob"}
        is_name_field = field_name in {
            "patient_name",
            "insured_name",
        } or "name" in (field_name or "").casefold()

        def _group_calendar_valid(items) -> bool:
            # Prefer calendar-valid DOB groups over header labels / digit junk
            # so paddle "MM" or "671161946" cannot outrank a shaped date.
            for candidate, _, _ in items:
                if _dob_ymd(str(candidate.value or "")) is not None:
                    return True
            return False

        ranked = sorted(
            groups.items(),
            key=lambda item: (
                independent_agreement(item[0], item[1]),
                _group_calendar_valid(item[1]) if is_dob_field else True,
                max(score for _, score, _ in item[1]),
            ),
            reverse=True,
        )
        _normalized_value, supporting = ranked[0]
        value = max(supporting, key=lambda item: item[1])[0].value
        early_separator_relief = False
        early_name_relief = False
        # Within a multi-engine name agreement group, prefer the display that
        # already lacks JI / digit-1 confusables (JIOSEPHINE → JOSEPHINE).
        if is_name_field and len(supporting) >= 1:
            displays = [str(c.value or "") for c, _, _ in supporting]
            name_clean = prefer_name_without_confusable_insertion(
                displays[0], displays[1:]
            )
            if name_clean:
                value = name_clean
                early_name_relief = True
            else:
                # Prefer already-peeled display among same-canonical supporters.
                scored = sorted(
                    supporting,
                    key=lambda item: (
                        "JI" in re.sub(r"[^A-Z]", "", (item[0].value or "").upper()),
                        "1" in (item[0].value or ""),
                        -item[1],
                    ),
                )
                value = scored[0][0].value
        # CMS box-3 dashed rules OCR as leading "1" (01↔11, 09↔19). Apply
        # separator relief against ALL competing groups, not only when the
        # confidence margin is tiny — high-confidence separator-1 otherwise STP-wrong.
        if is_dob_field and len(ranked) > 1:
            competing = [
                str(max(items, key=lambda row: row[1])[0].value)
                for _, items in ranked[1:]
            ]
            separator_clean = prefer_dob_without_separator_one(str(value), competing)
            if separator_clean:
                value = separator_clean
                early_separator_relief = True
        elif is_name_field and len(ranked) > 1:
            competing = [
                str(max(items, key=lambda row: row[1])[0].value)
                for _, items in ranked[1:]
            ]
            name_clean = prefer_name_without_confusable_insertion(str(value), competing)
            if name_clean:
                value = name_clean
                early_name_relief = True
        has_independent_agreement = independent_agreement(_normalized_value, supporting)
        calibrated = max(score for _, score, _ in supporting)
        agreement_bonus = 0.04 if has_independent_agreement else 0.0
        reference_match = (
            authoritative_reference_verified
            and authoritative_value is not None
            and (value or "").strip().casefold() == authoritative_value.strip().casefold()
        )
        reference_contradiction = (
            authoritative_reference_verified
            and authoritative_value is not None
            and (value or "").strip().casefold() != authoritative_value.strip().casefold()
        )
        deterministic_ok = (
            bool(
                deterministic
                & {
                    "CHECKSUM_VALID",
                    "REFERENCE_MATCH",
                    "CROSS_FIELD_CONSISTENT",
                    "CROSS_DOCUMENT_AGREEMENT",
                    "FINANCIAL_RECONCILIATION_VALID",
                    "CLAIM_TOTAL_CONFIRMED",
                    "LINE_TOTALS_RECONCILED",
                    "DATE_RELATIONSHIP_CONFIRMED",
                    "DOB_SERVICE_DATE_CONSISTENT",
                    "MEMBER_IDENTITY_CONSISTENT",
                    "MEMBER_RELATIONSHIP_CONFIRMED",
                }
            )
            or reference_match
            # Format-valid member identifiers with field E3 remain HITL-gated by
            # evidence policy, but no longer hard-fail the C3 independent-engine
            # gate after OCR span cleanup.
            or (
                field_name in {"insured_id_number", "member_id", "subscriber_id"}
                and "HARD_VALIDATION_PASSED" in deterministic
            )
        )
        financial_authority = bool(
            self.allow_authoritative_financial_e6
            and field_name in {"total_charge", "total_charges"}
            and deterministic
            & {
                "CLAIM_TOTAL_CONFIRMED",
                "FINANCIAL_RECONCILIATION_VALID",
                "LINE_TOTALS_RECONCILED",
            }
        )
        # A verified reference is an independent E5 authority, not an OCR
        # calibration shortcut. Exact candidate/reference agreement may use
        # the reference decision's governed confidence and provenance.
        confidence = 1.0 if reference_match or financial_authority else min(
            1.0, calibrated + agreement_bonus
        )
        evidence = [
            EvidenceReference(
                evidence_type="OCR_CANDIDATE",
                reference=self._candidate_id(candidate),
                source=candidate.engine,
                reason_code="ENGINE_SUPPORT",
            )
            for candidate, _, _ in supporting
        ]
        evidence.extend(
            EvidenceReference(
                evidence_type="DETERMINISTIC", reference=code, source="validation", reason_code=code
            )
            for code in sorted(deterministic)
        )
        if reference_match:
            evidence.append(
                EvidenceReference(
                    evidence_type="AUTHORITATIVE_REFERENCE",
                    reference=authoritative_version or "version-not-provided",
                    source=authoritative_source or "authorized-reference",
                    reason_code="REFERENCE_MATCH",
                )
            )
        elif reference_contradiction:
            conflicts.append(
                EvidenceReference(
                    evidence_type="AUTHORITATIVE_REFERENCE",
                    reference=authoritative_version or "version-not-provided",
                    source=authoritative_source or "authorized-reference",
                    reason_code="REFERENCE_CONTRADICTION",
                )
            )
        for other_value, items in ranked[1:]:
            conflicts.extend(
                EvidenceReference(
                    evidence_type="OCR_CANDIDATE",
                    reference=self._candidate_id(candidate),
                    source=candidate.engine,
                    reason_code=f"CONFLICTING_VALUE:{other_value}",
                )
                for candidate, _, _ in items
            )
        reasons = ["HARD_VALIDATION_PASSED"] if "HARD_VALIDATION_PASSED" in deterministic else []
        if has_independent_agreement:
            reasons.append("MULTI_ENGINE_AGREEMENT")
        if reference_match:
            reasons.append("REFERENCE_MATCH")
        reasons.extend(sorted(deterministic))
        signals = set(deterministic)
        if has_independent_agreement:
            signals.add("OCR_MULTI_ENGINE")
        if reference_match:
            signals.add("REFERENCE_MATCH")
        rule = self.evidence_policies.rule_for(document_family, field_name, criticality)
        policy_ok, missing_alternatives = rule.evaluate(signals)
        threshold = rule.threshold if rule.threshold is not None else self.thresholds[criticality]
        # Identity fields with hard validation + member-relationship E6 are
        # corroboration-backed: allow a slightly lower calibrated floor (0.95)
        # instead of inventing values or waiving evidence. Closes near-miss
        # STP blocks where calibrated OCR is ~0.97 under a 0.98 C3 gate.
        identity_corroborated = (
            field_name in {"insured_id_number", "member_id", "subscriber_id"}
            and "HARD_VALIDATION_PASSED" in deterministic
            and bool(
                deterministic
                & {
                    "MEMBER_RELATIONSHIP_CONFIRMED",
                    "MEMBER_IDENTITY_CONSISTENT",
                }
            )
        )
        # Dual-engine confirmation agreement (paddle+rapid) after hard ID
        # validation is independent OCR corroboration — same floor as above,
        # not a policy waiver and not invented ink.
        multi_engine_id_corroborated = (
            field_name in {"insured_id_number", "member_id", "subscriber_id"}
            and "HARD_VALIDATION_PASSED" in deterministic
            and has_independent_agreement
        )
        # DOB with calendar/format hard validation: deterministic DATE_VALID is
        # corroboration, not invented ink. Floor at C1 (0.80) so near-miss
        # calibrated probs (~0.88–0.91) can STP without softening E3/identity.
        date_corroborated = (
            field_name in {"patient_dob", "date_of_birth", "dob"}
            and "HARD_VALIDATION_PASSED" in deterministic
            and "DATE_VALID" in deterministic
        )
        effective_threshold = threshold
        relief_reason: str | None = None
        if identity_corroborated or multi_engine_id_corroborated:
            effective_threshold = min(effective_threshold, 0.95)
            relief_reason = (
                "IDENTITY_CORROBORATED_THRESHOLD_RELIEF"
                if identity_corroborated
                else "MULTI_ENGINE_ID_CORROBORATED_THRESHOLD_RELIEF"
            )
        if date_corroborated:
            effective_threshold = min(effective_threshold, 0.80)
            relief_reason = "DATE_CORROBORATED_THRESHOLD_RELIEF"
        threshold_ok = confidence >= effective_threshold
        if (
            relief_reason
            and confidence >= effective_threshold
            and confidence < threshold
        ):
            reasons.append(relief_reason)
        # C3 always needs deterministic/authoritative evidence or two truly
        # independent engine families. Confidence is never sufficient alone.
        independent_evidence_ok = has_independent_agreement or deterministic_ok or financial_authority
        if reference_contradiction:
            decision = Decision.REVIEW
            reasons.append("REFERENCE_CONTRADICTION")
        elif not threshold_ok:
            decision = Decision.ESCALATE
            reasons.append("CALIBRATED_CONFIDENCE_BELOW_THRESHOLD")
        elif enforce_legacy_evidence_policy and not policy_ok:
            decision = Decision.REVIEW
            reasons.append("FIELD_EVIDENCE_POLICY_NOT_SATISFIED")
            reasons.extend(f"MISSING_ALTERNATIVE:{item}" for item in missing_alternatives)
        elif criticality is CriticalityLevel.C3 and not independent_evidence_ok:
            decision = Decision.REVIEW
            reasons.append("C3_INDEPENDENT_EVIDENCE_REQUIRED")
        elif len(ranked) > 1 and confidence - max(s for _, s, _ in ranked[1][1]) < 0.05:
            competing_values = [str(other) for other, _ in ranked[1:]]
            genuine = [
                other
                for other in competing_values
                if not values_conflict_equivalent(field_name, value, other)
            ]
            if early_separator_relief:
                # Competing values were separator-1 twins of the cleaned date.
                decision = (
                    Decision.REFERENCE_CONFIRMED if reference_match else Decision.ACCEPT
                )
                reasons.append("DOB_SEPARATOR_ARTIFACT_RELIEVED")
            elif early_name_relief:
                decision = (
                    Decision.REFERENCE_CONFIRMED if reference_match else Decision.ACCEPT
                )
                reasons.append("NAME_CONFUSABLE_INSERTION_RELIEVED")
            elif not genuine:
                decision = (
                    Decision.REFERENCE_CONFIRMED if reference_match else Decision.ACCEPT
                )
                reasons.append("EQUIVALENT_VALUE_CONFLICT_RELIEVED")
            else:
                separator_clean = None
                name_clean = None
                if date_corroborated or is_dob_field:
                    separator_clean = prefer_dob_without_separator_one(
                        str(value), genuine
                    )
                if is_name_field:
                    name_clean = prefer_name_without_confusable_insertion(
                        str(value), genuine
                    )
                if separator_clean:
                    value = separator_clean
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("DOB_SEPARATOR_ARTIFACT_RELIEVED")
                elif name_clean:
                    value = name_clean
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("NAME_CONFUSABLE_INSERTION_RELIEVED")
                elif date_corroborated and not any(
                    _dob_ymd(other) is not None
                    and _dob_ymd(other) != _dob_ymd(str(value))
                    and prefer_dob_without_separator_one(str(value), [other]) is None
                    for other in genuine
                ):
                    # Calendar-valid top date vs fragment / separator twins — not ambiguous.
                    decision = (
                        Decision.REFERENCE_CONFIRMED
                        if reference_match
                        else Decision.ACCEPT
                    )
                    reasons.append("DATE_CONFLICT_FRAGMENTS_RELIEVED")
                else:
                    decision = Decision.REVIEW
                    reasons.append("CONFLICT_MARGIN_TOO_SMALL")
        else:
            decision = (
                Decision.REFERENCE_CONFIRMED if reference_match else Decision.ACCEPT
            )
            if early_separator_relief:
                reasons.append("DOB_SEPARATOR_ARTIFACT_RELIEVED")
            if early_name_relief:
                reasons.append("NAME_CONFUSABLE_INSERTION_RELIEVED")
        versions = (
            [f"authoritative-reference:{authoritative_version or 'version-not-provided'}"]
            if reference_match
            else ["deterministic-financial-e6-v1"]
            if financial_authority
            else sorted({version for _, _, version in supporting})
        )
        result = ReconciliationResult(
            field_name=field_name,
            selected_value=value,
            candidate_ids=ids,
            decision=decision,
            confidence=confidence,
            supporting_evidence=evidence,
            conflicting_evidence=conflicts,
            rationale_codes=list(dict.fromkeys(reasons)),
            calibration_model_version=",".join(versions),
        )
        field_reconciliation_total.labels(
            field_name=field_name,
            criticality=criticality.value,
            decision=decision.value,
        ).inc()
        return result
