from __future__ import annotations

from difflib import SequenceMatcher

from packages.reference_enrichment.contracts import ReferenceLookupRequest, ReferenceRecord


def _norm(value: str | None) -> str:
    return "".join(char for char in (value or "").upper() if char.isalnum())


def match_member(request: ReferenceLookupRequest, record: ReferenceRecord) -> tuple[list[str], dict[str, float], list[str], bool]:
    claim = request.available_claim_attributes
    ref = record.reference_attributes
    matched: list[str] = []
    contradictions: list[str] = []
    scores: dict[str, float] = {}
    for key in ("member_id", "dob", "zip"):
        left, right = _norm(claim.get(key)), _norm(ref.get(key))
        if left and right:
            scores[key] = float(left == right)
            (matched if left == right else contradictions).append(key)
    left_name, right_name = _norm(claim.get("name")), _norm(ref.get("name"))
    if left_name and right_name:
        scores["name"] = SequenceMatcher(None, left_name, right_name).ratio()
        (matched if scores["name"] >= 0.92 else contradictions).append("name")
    member_dob = scores.get("member_id") == 1 and scores.get("dob") == 1
    fallback = scores.get("dob") == 1 and scores.get("name", 0) >= 0.92 and scores.get("zip") == 1
    return matched, scores, contradictions, bool((member_dob or fallback) and not contradictions)
