"""Deterministic same-page OCR candidate reconciliation."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class ReconciliationDecision:
    value: str | None
    score: float
    margin: float
    ambiguous: bool
    reason: str
    diagnostics: tuple[dict, ...] = ()


def _engine_family(provider: str) -> str:
    provider = provider.lower()
    for family in ("pixel", "trocr", "paddle", "tesseract"):
        if family in provider:
            return family
    return provider


_FORM_LABEL_PATTERN = re.compile(
    r"\b(?:PATIENT'?S?|ADDRESS|BIRTH\s*DATE|ADMISSION|SEX|STREET|"
    r"CITY|STATEA?|STAEA|ZIP\s*CODE|INSURED|CLAIM)\b",
    re.IGNORECASE,
)


def _valid(field: str, value: str) -> bool:
    if not value:
        return False
    if field == "rel_code":
        return value.upper() in {"01", "02", "19", "G8", "09"}
    if field == "patient_sex":
        return value.upper() in {"M", "F", "U"}
    if field.endswith("_state"):
        return bool(re.fullmatch(r"[A-Za-z]{2}", value))
    if field in {"federal_tax_id", "federal_tax_no"}:
        return bool(re.fullmatch(r"\d{9}", value))
    if field.endswith("_zip"):
        return value != "999999999" and bool(re.fullmatch(r"\d{5}|\d{9}", value))
    if field in {"insured_addr1", "insured_addr2", "insured_city"} and value.upper() == "NA":
        return False
    if field in {"patient_first", "patient_last"}:
        if _FORM_LABEL_PATTERN.search(value):
            return False
        # A component parser must not return an entire name or form fragment.
        if len(value.split()) > 2 or any(char.isdigit() for char in value):
            return False
        return bool(re.fullmatch(r"[A-Za-z][A-Za-z'.-]*", value.strip(" ,")))
    if field.endswith(("addr1", "addr2")):
        if _FORM_LABEL_PATTERN.search(value):
            return False
        # A street-address component cannot consist only of a house number or
        # punctuation. Require both numeric and alphabetic regional evidence.
        if not (re.search(r"\d", value) and re.search(r"[A-Za-z]", value)):
            return False
    if field.endswith("_city"):
        return bool(re.fullmatch(r"[A-Za-z .'-]{2,}", value)) and value.upper() not in {
            "CITY", "STATE", "ZIP CODE",
        }
    return True


def reconcile_candidates(
    field_name: str,
    candidates: list[dict],
    *,
    minimum_score: float = 0.45,
    minimum_margin: float = 0.08,
) -> ReconciliationDecision:
    complete_tag = (
        "complete_name_block_component"
        if field_name in {"patient_first", "patient_last"}
        else "complete_address_block_component"
        if field_name.startswith(("insured_", "patient_")) and field_name.endswith(
            ("addr1", "addr2", "city", "state", "zip")
        )
        else None
    )
    # Complete-block components receive deterministic priority below, but do
    # not suppress independently generated regional evidence. A malformed
    # block parse must never erase a correct OCR candidate.
    # Parser output only dominates generic text derived from the same evidence.
    # It must not globally suppress independent engines/crops.
    parsed_evidence = {
        (
            item.get("provider"),
            item.get("preprocessing_variant"),
            tuple(item.get("raw", [])),
        )
        for item in candidates
        if "person_name_component" in item.get("validation_results", [])
    }
    groups: dict[str, list[dict]] = defaultdict(list)
    for candidate in candidates:
        if candidate.get("evidence_role") == "ROUTING_ONLY":
            continue
        evidence_key = (
            candidate.get("provider"),
            candidate.get("preprocessing_variant"),
            tuple(candidate.get("raw", [])),
        )
        if (
            evidence_key in parsed_evidence
            and "person_name_component" not in candidate.get("validation_results", [])
        ):
            continue
        if "fixed_width_output_projection" in candidate.get("validation_results", []):
            continue
        value = str(candidate.get("value") or "").strip()
        if field_name.endswith("_city"):
            value = re.sub(r"\s+", "", value)
        if field_name in {"patient_first", "patient_last"}:
            value = value.strip("[](),.- ")
        if _valid(field_name, value):
            groups[value.upper()].append(candidate)
    if not groups:
        return ReconciliationDecision(None, 0.0, 0.0, False, "NO_VALID_VALUE", ())
    def engine_family(item):
        return _engine_family(item.get("engine") or item.get("provider", ""))

    total_families = {engine_family(item) for group in groups.values() for item in group}
    total_candidates = sum(len(group) for group in groups.values())
    ranked = []
    for normalized, group in groups.items():
        families = {engine_family(item) for item in group}
        validations = {
            result for item in group for result in item.get("validation_results", [])
        }
        consensus = len(families) / max(1, len(total_families))
        provider_component = min(0.60, 0.20 * len(families))
        consensus_component = 0.20 * consensus
        support_component = 0.15 * len(group) / max(1, total_candidates)
        score = provider_component + consensus_component + support_component
        validation_component = 0.0
        if validations & {
            "person_name_component", "single_mark", "winning_margin",
            "length_9", "npi_checksum", "calendar_date", "format_valid",
            "fixed_width_output_projection",
            "complete_name_block_component", "complete_address_block_component",
        }:
            validation_component = 0.25
            score += validation_component
        lineage_component = 0.0
        if complete_tag and complete_tag in validations:
            lineage_component = 0.10
            score += lineage_component
        pixel_component = 0.0
        if any("pixel" in item.get("provider", "").lower() for item in group):
            pixel_component = 0.20
            score += pixel_component
        page_token_component = 0.0
        if any("page_token_recovery" in item.get("provider", "") for item in group):
            page_token_component = 0.10
            score += page_token_component
        ranked.append((normalized, min(score, 1.0), group, {
            "value": normalized,
            "eligible": True,
            "provider_families": sorted(families),
            "engine_agreement": len(families),
            "hard_validation_results": sorted(validations),
            "score_components": {
                "provider": provider_component,
                "consensus": consensus_component,
                "support": support_component,
                "validation": validation_component,
                "pixel_mark": pixel_component,
                "page_token": page_token_component,
                "parser_lineage": lineage_component,
            },
            "final_score": min(score, 1.0),
        }))
    ranked.sort(key=lambda item: (item[1], len(item[2])), reverse=True)
    value, score, group, _diagnostic = ranked[0]
    runner = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = score - runner
    diagnostics = tuple(item[3] for item in ranked)
    if len(ranked) > 1 and margin < minimum_margin:
        return ReconciliationDecision(None, score, margin, True, "AMBIGUOUS_VALUE", diagnostics)
    if score < minimum_score:
        return ReconciliationDecision(None, score, margin, False, "BELOW_VALUE_THRESHOLD", diagnostics)
    return ReconciliationDecision(group[0]["value"], score, margin, False, "SELECTED", diagnostics)
