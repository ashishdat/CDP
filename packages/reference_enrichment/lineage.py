from __future__ import annotations

from packages.reference_enrichment.contracts import ReferenceRecord

FORBIDDEN_ORIGINS = {"extraction-v2", "azure-fallback", "unreviewed-ocr", "cdp-prediction"}


def lineage_violations(record: ReferenceRecord) -> list[str]:
    lineage = {item.lower() for item in record.source_lineage}
    violations = [f"CIRCULAR_ORIGIN:{item}" for item in sorted(lineage & FORBIDDEN_ORIGINS)]
    if not record.source_lineage:
        violations.append("LINEAGE_UNKNOWN")
    if not record.independent_truth:
        violations.append("NOT_INDEPENDENT_TRUTH")
    if not record.non_circular_lineage:
        violations.append("NON_CIRCULAR_LINEAGE_NOT_CONFIRMED")
    return violations
