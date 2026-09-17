"""Deterministic, read-only adjudication of saved ExtractionResult artifacts.

AutoTruth is derived evidence agreement, never independent ground truth.
No OCR, registration, geometry, LLM, or production writes are performed.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

CHANNELS = ("ocr", "ranking", "validator", "business_rules",
            "registration_confidence", "geometry_confidence", "historical_pattern",
            "cross_field_validation")
STATUSES = ("AUTO_VERIFIED", "REVIEW_REQUIRED", "CONFLICT", "UNKNOWN")


def observation(state="UNKNOWN", reason="No recorded evidence", **details):
    if state not in {"SUPPORT", "CONTRADICT", "UNKNOWN"}:
        raise ValueError("Invalid evidence state")
    return {"state": state, "reason": reason, **details}


class AutoAdjudicationEngine:
    """All eight sources must explicitly support the selected value.

    CONTRADICT means evidence conflict (REVIEW_REQUIRED). CONFLICT as a
    field status means broken candidate lineage: attribution is unsafe.
    Confidence is evidence agreement coverage, not a calibrated probability.
    """

    def adjudicate(self, field_name, value, evidence, *, integrity_errors=()):
        if set(evidence) != set(CHANNELS):
            raise ValueError("Exactly eight evidence channels required")
        if any(e.get("state") not in {"SUPPORT", "CONTRADICT", "UNKNOWN"}
               for e in evidence.values()):
            raise ValueError("Invalid evidence state")
        conflicts = [k for k, e in evidence.items() if e["state"] == "CONTRADICT"]
        missing = [k for k, e in evidence.items() if e["state"] == "UNKNOWN"]
        empty = value is None or (isinstance(value, str) and not value.strip())
        if integrity_errors:
            status = "CONFLICT"
        elif conflicts:
            status = "REVIEW_REQUIRED"
        elif empty:
            status = "UNKNOWN"
        elif not missing:
            status = "AUTO_VERIFIED"
        else:
            status = "REVIEW_REQUIRED"
        confidence = (0.0 if conflicts or integrity_errors or empty else
                      100 * sum(e["state"] == "SUPPORT" for e in evidence.values()) / len(CHANNELS))
        return {"field_name": field_name, "value": value, "status": status,
                "confidence": confidence,
                "evidence_state": "CONFLICT" if conflicts or integrity_errors else
                    ("UNKNOWN" if missing or empty else "AGREEMENT"),
                "review_required": status != "AUTO_VERIFIED",
                "conflicting_sources": conflicts, "missing_sources": missing,
                "integrity_errors": list(integrity_errors), "evidence": evidence}


def field_evidence(field, decision=None):
    """Adapt recorded outputs; never manufacture absent confidence or history."""
    name, value = field["field_name"], field["normalized_value"]
    winner, validation = field["ranked_candidate"], field["validation"]
    evidence = {k: observation() for k in CHANNELS}
    errors = []
    rows = ([winner] if winner else []) + field.get("alternatives", [])
    candidates = field["ocr"]["candidates"]
    checks = field.get("candidate_validations", [])
    if not winner:
        if candidates or validation is not None or rows or field["status"] != "NO_VALUE":
            errors.append("Inconsistent missing winner")
    else:
        if (not winner.get("is_winner") or winner.get("winner") != winner.get("candidate_id")
                or winner.get("field_id") != name or validation is None
                or validation.get("field_id") != name
                or validation.get("candidate_id") != winner.get("candidate_id")
                or validation.get("normalized_value") != value
                or validation.get("status") != field["status"]):
            errors.append("Winner/validation lineage mismatch")
        if winner.get("ocr_candidate") not in candidates:
            errors.append("Winner absent from OCR observations")
        if len({r["candidate_id"] for r in rows}) != len(rows):
            errors.append("Duplicate candidate identity")
        if any(r.get("field_id") != name or r.get("winner") != winner["candidate_id"]
               or (r is not winner and r.get("is_winner")) for r in rows):
            errors.append("Inconsistent ranking lineage")
        if len(checks) != len(rows) or {v["candidate_id"] for v in checks} != {r["candidate_id"] for r in rows}:
            errors.append("Candidate validation coverage mismatch")
        raw = winner.get("ocr_candidate", {})
        if raw.get("raw_value") is not None and str(raw["raw_value"]).strip():
            evidence["ocr"] = observation("SUPPORT", "Saved OCR observation backs winner; not accuracy evidence",
                raw_confidence=raw.get("raw_confidence"), provider=raw.get("engine"))
        evidence["ranking"] = observation("SUPPORT", "Recorded winner", candidate_id=winner.get("candidate_id"))
        if validation:
            vstatus = validation["status"]
            state = "SUPPORT" if vstatus == "VALID" else ("CONTRADICT" if vstatus in
                    {"INVALID", "AMBIGUOUS", "SUSPICIOUS"} else "UNKNOWN")
            evidence["validator"] = observation(state, "Saved validator result", status=vstatus,
                validator=validation.get("validator"), reasons=validation.get("reason"))
        # Compare saved normalized candidate values; never compare raw formatting
        # to normalized text as if it were a semantic contradiction.
        if any(v.get("field_id") != name for v in checks):
            errors.append("Validation field mismatch")
        if any(v.get("status") == "VALID" and v.get("normalized_value") != value for v in checks):
            evidence["ranking"] = observation("CONTRADICT", "Valid alternative disagrees with winner")
        evidence["registration_confidence"] = observation(reason="No existing confidence acceptance verdict in ExtractionResult",
            recorded_confidence=raw.get("registration_confidence"))
    if decision:
        check = decision.get("deterministic_checks", {}).get(name)
        if check:
            state = {"PASS": "SUPPORT", "FAIL": "CONTRADICT"}.get(check["status"], "UNKNOWN")
            evidence["business_rules"] = observation(state, "Existing saved deterministic rule result", recorded=check)
        facts = decision.get("claim_facts", {})
        support = [x for x in facts.get("evidence_items", []) if name in x.get("metadata", {}).get("supported_fields", [])]
        against = [x for x in facts.get("contradictions", []) if name in x.get("metadata", {}).get("supported_fields", [])]
        cross = (check or {}).get("cross_field_evidence", [])
        if against or support or cross:
            evidence["cross_field_validation"] = observation("CONTRADICT" if against else "SUPPORT",
                "Saved cross-field results", supporting=support, conflicting=against, deterministic=cross)
        # Existing downstream policy veto is also business-rule evidence.
        fd = next((x for x in decision.get("field_decisions", []) if x["field_name"] == name), None)
        if fd and fd.get("disposition") in {"REJECTED", "HUMAN_REVIEW_REQUIRED", "ESCALATE"}:
            evidence["business_rules"] = observation("CONTRADICT" if fd["disposition"] == "REJECTED" else "UNKNOWN",
                "Existing field policy requires review/rejection",
                disposition=fd["disposition"], reasons=fd.get("reason_codes", []), deterministic_check=check)
    return evidence, errors


def load_extraction(path):
    path = Path(path)
    payload = path.read_bytes()
    extraction = json.loads(payload)
    if extraction.get("type") != "ExtractionResult" or extraction.get("status") != "ASSEMBLED":
        raise ValueError("Assembled ExtractionResult required")
    fields = extraction["field_results"]
    if not fields or len({f["field_name"] for f in fields}) != len(fields):
        raise ValueError("Nonempty unique fields required")
    for reference in extraction.get("source_artifacts", {}).values():
        if sha256(Path(reference["path"]).read_bytes()).hexdigest() != reference["sha256"]:
            raise ValueError("Source artifact hash mismatch")
    decision_path = path.parent.parent / "DecisionResult.json"
    decision = None
    if decision_path.exists():
        decision = json.loads(decision_path.read_bytes())
        if (decision.get("status") != "SUCCESS" or decision.get("type") != "DecisionResult"
                or decision.get("extraction_reference", {}).get("sha256") != sha256(payload).hexdigest()
                or decision.get("document") != extraction["document"]
                or decision.get("page") != extraction["page"]
                or decision.get("extracted_fields") != fields):
            raise ValueError("Saved decision/extraction lineage mismatch")
    engine = AutoAdjudicationEngine()
    results = []
    for field in fields:
        evidence, errors = field_evidence(field, decision)
        if extraction.get("errors"):
            errors.append("ExtractionResult contains errors")
        results.append(engine.adjudicate(field["field_name"], field["normalized_value"], evidence, integrity_errors=errors))
    return {"document": extraction["document"], "page": extraction["page"],
            "source": {"path": str(path), "sha256": sha256(payload).hexdigest()},
            "decision_source": {"path": str(decision_path), "sha256": sha256(decision_path.read_bytes()).hexdigest()} if decision else None,
            "fields": results}


def build_report(paths):
    documents = [load_extraction(p) for p in paths]
    identities = [(d["document"]["document_id"], d["page"]["page_number"]) for d in documents]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate document/page input")
    fields = [f for d in documents for f in d["fields"]]
    if not fields:
        raise ValueError("At least one field required")
    counts = Counter(f["status"] for f in fields)
    conflict = sum(f["evidence_state"] == "CONFLICT" for f in fields)
    return {"type": "AutoTruth", "policy_version": "deterministic-agreement-v1",
            "ground_truth": False, "confidence_basis": "0-100 agreement coverage across eight required sources; zero for conflicts/missing values. Not probability of correctness.",
            "status_semantics": {"AUTO_VERIFIED": "All eight recorded sources support the value",
                "REVIEW_REQUIRED": "Incomplete or contradictory evidence", "CONFLICT": "Unsafe evidence lineage; review required",
                "UNKNOWN": "No selected value; review required"},
            "metrics": {"documents": len(documents), "fields": len(fields),
                "status_counts": {s: counts[s] for s in STATUSES},
                "auto_verification_rate": 100 * counts["AUTO_VERIFIED"] / len(fields),
                "conflict_rate": 100 * conflict / len(fields),
                "review_rate": 100 * sum(f["review_required"] for f in fields) / len(fields),
                "rate_unit": "percent of input fields", "conflict_fields": conflict,
                "note": "Conflict rate overlaps review rate; UNKNOWN also requires review."},
            "limitations": ["Derived agreement cannot replace independently verified validation labels.",
                "Shared upstream evidence is correlated, not independent confirmation.",
                "Absent historical patterns, geometry confidence or confidence acceptance verdicts remain UNKNOWN.",
                "No runtime stages or evidence acquisition were executed."], "documents": documents}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extractions", nargs="+")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = build_report(args.extractions)
    with Path(args.output).open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report["metrics"]))
