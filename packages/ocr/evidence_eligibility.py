"""Eligibility for confirmation, shared by typed and raw candidate paths."""
from collections.abc import Mapping


def confirmation_eligible(candidate):
    if candidate is None:
        return False
    if isinstance(candidate, Mapping):
        if candidate.get("prior_hints_supplied") or candidate.get("shadow_review_only"):
            return False
        nested = candidate.get("ocr_candidate")
        return confirmation_eligible(nested) if isinstance(nested, Mapping) else True
    return not (getattr(candidate, "prior_hints_supplied", False)
                or getattr(candidate, "shadow_review_only", False))


def eligible_candidates(candidates):
    return [candidate for candidate in candidates or [] if confirmation_eligible(candidate)]
