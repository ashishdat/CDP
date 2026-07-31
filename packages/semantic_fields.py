"""Semantic source state is distinct from visible OCR and output projection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SemanticFieldState(StrEnum):
    PRESENT = "PRESENT"
    BLANK = "BLANK"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SAME_AS_PATIENT = "SAME_AS_PATIENT"
    SAME_AS_INSURED = "SAME_AS_INSURED"
    UNKNOWN = "UNKNOWN"
    UNREADABLE = "UNREADABLE"
    DERIVED_UNVERIFIED = "DERIVED_UNVERIFIED"


@dataclass(frozen=True)
class SemanticFieldValue:
    field_name: str
    semantic_state: SemanticFieldState
    source_value: str | None
    output_value: str | None
    rule_id: str | None
    rule_version: str | None
    evidence_references: tuple[str, ...]
    validated: bool

    @property
    def raw_ocr_value(self) -> str | None:
        return self.source_value

    @property
    def normalized_source_value(self) -> str | None:
        return self.source_value

    @property
    def projected_output_value(self) -> str | None:
        return self.output_value

    @property
    def projection_rule_id(self) -> str | None:
        return self.rule_id

    @property
    def projection_rule_version(self) -> str | None:
        return self.rule_version


@dataclass(frozen=True)
class SentinelProjectionRule:
    rule_id: str
    version: str
    field_name: str
    required_state: SemanticFieldState
    output_value: str
    authorization: str
    specification_reference: str | None = None


def project_output_sentinel(
    semantic: SemanticFieldValue, rule: SentinelProjectionRule
) -> SemanticFieldValue:
    if rule.authorization != "approved":
        raise ValueError(f"{rule.rule_id} is not an approved runtime business rule")
    if not rule.specification_reference:
        raise ValueError(f"{rule.rule_id} lacks a specification/business-rule reference")
    if semantic.field_name != rule.field_name:
        raise ValueError("sentinel rule applies to a different field")
    if semantic.semantic_state != rule.required_state or not semantic.validated:
        raise ValueError("semantic state has not satisfied the sentinel rule")
    return SemanticFieldValue(
        field_name=semantic.field_name,
        semantic_state=semantic.semantic_state,
        source_value=semantic.source_value,
        output_value=rule.output_value,
        rule_id=rule.rule_id,
        rule_version=rule.version,
        evidence_references=semantic.evidence_references,
        validated=True,
    )


def infer_same_as_state(
    *,
    field_name: str,
    source_value: str | None,
    counterpart_value: str | None,
    relationship_code: str | None,
    counterpart: SemanticFieldState,
    evidence_references: tuple[str, ...],
) -> SemanticFieldValue:
    """Infer same-as only from SELF relationship and one-sided document evidence."""
    if counterpart not in {
        SemanticFieldState.SAME_AS_PATIENT,
        SemanticFieldState.SAME_AS_INSURED,
    }:
        raise ValueError("counterpart must be a SAME_AS semantic state")
    validated = (
        relationship_code == "01"
        and not (source_value or "").strip()
        and bool((counterpart_value or "").strip())
    )
    return SemanticFieldValue(
        field_name=field_name,
        semantic_state=counterpart if validated else SemanticFieldState.UNKNOWN,
        source_value=source_value,
        output_value=counterpart_value if validated else None,
        rule_id="CMS1500_SELF_ONE_SIDED_EVIDENCE" if validated else None,
        rule_version="1.0" if validated else None,
        evidence_references=evidence_references,
        validated=validated,
    )
