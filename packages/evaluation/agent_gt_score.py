"""Agent-GT scoring for product FA gates (accepted-field precision).

Product bar: FA=0 on GOLD criticals after representation-only exact match
and quarantine ledger exclusions. SILVER labels are prior AUTO echoes and
are not used for the green FA gate.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence


_AUTO = frozenset(
    {
        "AUTO_ACCEPTED",
        "REFERENCE_CONFIRMED",
        "HUMAN_CONFIRMED",
        "ACCEPTED",
        "AUTO",
    }
)

_CRITICAL = frozenset(
    {
        "patient_name",
        "patient_dob",
        "insured_id_number",
        "total_charge",
        "insured_name",
    }
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QUARANTINE = ROOT / "docs" / "gt" / "ground_truth_discrepancy_ledger.json"


def _claim_keys(claim_id: str) -> set[str]:
    text = str(claim_id or "")
    tail = text.replace("\\", "/").split("/")[-1]
    return {text, text.replace("/", "__"), text.replace("__", "/"), tail}


@lru_cache(maxsize=2)
def load_quarantine(path: str | None = None) -> frozenset[tuple[str, str]]:
    ledger = Path(path) if path else DEFAULT_QUARANTINE
    if not ledger.is_file():
        return frozenset()
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    out: set[tuple[str, str]] = set()
    for record in payload.get("records") or []:
        if not record.get("quarantine_from_accuracy", True):
            continue
        field = record.get("field_name")
        if not field:
            continue
        for key in _claim_keys(str(record.get("claim_id") or "")):
            out.add((key, str(field)))
    return frozenset(out)


def _quarantined(
    claim_id: str,
    field: str,
    table: frozenset[tuple[str, str]] | None = None,
) -> bool:
    blocked = table if table is not None else load_quarantine()
    return any((key, field) in blocked for key in _claim_keys(claim_id))


def _canon_date(value: object) -> str:
    text = str(value or "").strip()
    digits = re.sub(r"\D", "", text)
    if len(digits) == 8:
        if int(digits[0:4]) >= 1880:
            return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
        return f"{digits[4:8]}-{digits[0:2]}-{digits[2:4]}"
    if len(digits) == 6:
        yy = int(digits[4:6])
        century = 1900 if yy >= 30 else 2000
        return f"{century + yy:04d}-{digits[0:2]}-{digits[2:4]}"
    return text.upper()


def _compact_alnum(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _is_same_marker(value: object) -> bool:
    compact = _compact_alnum(value)
    if compact == "SAME":
        return True
    return bool(re.fullmatch(r"SAME\d{1,2}", compact))


def exact_match(
    field: str,
    predicted: object,
    expected: object,
    *,
    patient_name: object | None = None,
) -> bool:
    """Representation normalization only — no OCR repairs or identity deletion."""
    if expected in (None, "", "EMPTY", "NULL"):
        return predicted is None or str(predicted).strip() == ""
    if field in {"patient_dob", "date_of_birth"}:
        return _canon_date(predicted) == _canon_date(expected)
    if field in {"total_charge", "total_charges"}:
        try:
            from packages.claim_evidence.line_sum_authority import parse_currency

            a, b = parse_currency(predicted), parse_currency(expected)
            return a is not None and b is not None and a == b
        except Exception:  # noqa: BLE001
            try:
                a = float(str(predicted).replace(",", "").replace("$", "").strip())
                b = float(str(expected).replace(",", "").replace("$", "").strip())
                return abs(a - b) < 1e-6
            except ValueError:
                return False
    if field in {"insured_id_number", "member_id"}:
        a, b = _compact_alnum(predicted), _compact_alnum(expected)
        if a == b:
            return True
        if a.isdigit() and b.isdigit():
            return (a.lstrip("0") or "0") == (b.lstrip("0") or "0")
        return False
    if field in {"patient_name", "insured_name"}:
        # CMS Box 4 "SAME" is a self-reference, not a person string.
        if _is_same_marker(expected) or _is_same_marker(predicted):
            if patient_name is None or not str(patient_name).strip():
                return _is_same_marker(predicted) and _is_same_marker(expected)
            left = predicted if not _is_same_marker(predicted) else patient_name
            right = expected if not _is_same_marker(expected) else patient_name
            if _compact_alnum(left) == _compact_alnum(right):
                return True
            try:
                from packages.candidate_reconciliation.reconciler import (
                    _names_differ_by_optional_middle_initial,
                )

                return _names_differ_by_optional_middle_initial(
                    str(left or ""), str(right or "")
                )
            except Exception:  # noqa: BLE001
                return False
        if _compact_alnum(predicted) == _compact_alnum(expected):
            return True
        try:
            from packages.candidate_reconciliation.reconciler import (
                _names_differ_by_optional_middle_initial,
            )

            return _names_differ_by_optional_middle_initial(
                str(predicted or ""), str(expected or "")
            )
        except Exception:  # noqa: BLE001
            return False
    return str(predicted or "").strip().upper() == str(expected or "").strip().upper()


def normalize_field(field_name: str, value: str) -> str:
    """Legacy helper — prefer exact_match for FA gates."""
    key = (field_name or "").casefold()
    if key in {"patient_name", "insured_name"}:
        return _compact_alnum(value)
    if key in {"patient_dob", "date_of_birth"}:
        return _canon_date(value)
    if key in {"insured_id_number", "member_id", "subscriber_id"}:
        compact = _compact_alnum(value)
        if compact.isdigit():
            return compact.lstrip("0") or "0"
        return compact
    if key in {"total_charge", "total_charges", "charges"}:
        raw = (value or "").replace(",", "").strip().lstrip("$")
        try:
            return f"{float(raw):.2f}"
        except ValueError:
            return raw
    return (value or "").strip().casefold()


def load_agent_gt(
    path: Path,
    *,
    gold_only: bool = False,
) -> dict[str, dict[str, dict[str, str]]]:
    """Return claim_id → {field_name: {expected_value, confidence, ...}}."""
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_claim: dict[str, dict[str, dict[str, str]]] = {}

    def _truth_meta(raw: object) -> dict[str, str] | None:
        if raw is None:
            return None
        if isinstance(raw, Mapping):
            value = None
            for key in ("expected_value", "value", "truth", "label"):
                if raw.get(key) is not None:
                    value = str(raw.get(key))
                    break
            if value is None:
                return None
            conf = str(raw.get("confidence") or "SILVER").upper()
            if gold_only and conf != "GOLD":
                return None
            return {
                "expected_value": value,
                "confidence": conf,
                "source": str(raw.get("source") or ""),
            }
        if gold_only:
            return None
        return {"expected_value": str(raw), "confidence": "SILVER", "source": ""}

    claims = payload.get("claims") if isinstance(payload, Mapping) else payload
    if isinstance(claims, list):
        for row in claims:
            if not isinstance(row, Mapping):
                continue
            cid = str(row.get("claim_id") or row.get("document") or "")
            field = str(row.get("field_name") or "")
            meta = _truth_meta(
                row.get("value")
                or row.get("truth")
                or row.get("label")
                or row.get("expected_value")
                or row
            )
            if not cid or not field or meta is None:
                continue
            if field not in _CRITICAL:
                continue
            for key in _claim_keys(cid):
                by_claim.setdefault(key, {})[field] = meta
        return by_claim

    if isinstance(claims, Mapping):
        for cid, body in claims.items():
            if not isinstance(body, Mapping):
                continue
            fields = body.get("fields") if isinstance(body.get("fields"), Mapping) else body
            if not isinstance(fields, Mapping):
                continue
            packed: dict[str, dict[str, str]] = {}
            for name, raw in fields.items():
                if str(name) not in _CRITICAL:
                    continue
                meta = _truth_meta(raw)
                if meta is None:
                    continue
                packed[str(name)] = meta
            if not packed:
                continue
            for key in _claim_keys(str(cid)):
                by_claim[key] = packed
            doc = body.get("document")
            if doc:
                for key in _claim_keys(str(doc)):
                    by_claim[key] = packed
    return by_claim


def _accepted_values_from_decision(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    for fd in payload.get("field_decisions") or []:
        if not isinstance(fd, Mapping):
            continue
        name = str(fd.get("field_name") or "")
        if name not in _CRITICAL:
            continue
        disp = str(fd.get("disposition") or "")
        if disp not in _AUTO:
            continue
        value = fd.get("selected_value")
        if value is None or not str(value).strip():
            continue
        out[name] = str(value)
    return out


def _accepted_values_from_row(
    row: Mapping[str, Any],
    *,
    claim_roots: Sequence[Path] | None = None,
) -> dict[str, str]:
    out: dict[str, str] = {}
    meta = row.get("unstructured_reg_fallback") or {}
    fields = meta.get("fields") if isinstance(meta, Mapping) else None
    if isinstance(fields, Mapping) and row.get("disposition") == "TRUE_STP":
        for name, value in fields.items():
            if name in _CRITICAL and str(value or "").strip():
                out[str(name)] = str(value)
    accepted = row.get("accepted_fields") or row.get("critical_values")
    if isinstance(accepted, Mapping):
        for name, value in accepted.items():
            if name in _CRITICAL and str(value or "").strip():
                out[str(name)] = str(value)
    # Prefer nested result.fields when present on the ledger row.
    nested = row.get("fields")
    if isinstance(nested, Mapping):
        for name, body in nested.items():
            if name not in _CRITICAL:
                continue
            if isinstance(body, Mapping):
                disp = str(body.get("disp") or body.get("disposition") or "")
                if disp and disp not in _AUTO:
                    continue
                value = body.get("value") or body.get("selected_value")
            else:
                value = body
            if value is None or not str(value).strip():
                continue
            out[str(name)] = str(value)
    # Prefer DecisionResult when present (registered CMS path).
    claim_id = str(row.get("claim_id") or "")
    for root in claim_roots or ():
        decision = root / claim_id / "final" / "DecisionResult.json"
        decided = _accepted_values_from_decision(decision)
        if decided:
            out.update(decided)
            break
    return out


def score_merged_against_agent_gt(
    merged_rows: Mapping[str, Mapping[str, Any]],
    gt_path: Path,
    *,
    critical_only: bool = True,
    claim_roots: Sequence[Path] | None = None,
    gold_only: bool = True,
    apply_quarantine: bool = True,
) -> dict[str, Any]:
    """Score accepted critical fields vs agent GT. FA=0 is the product bar."""
    gt = load_agent_gt(Path(gt_path), gold_only=gold_only)
    if not gt:
        return {
            "status": "GT_MISSING",
            "gt_path": str(gt_path),
            "claims_scored": 0,
            "accepted_fields_scored": 0,
            "false_accepts": 0,
            "exact_matches": 0,
            "accepted_field_precision": None,
            "baseline_false_accepts": 0,
            "gold_only": gold_only,
            "quarantine_applied": apply_quarantine,
        }

    roots = list(claim_roots or [])
    if not roots:
        roots = [
            ROOT / "evaluation_results" / "hackathon_600_independent_v13c" / "claims",
            ROOT
            / "evaluation_results"
            / "hackathon_400_remainder_independent_v13c"
            / "claims",
        ]

    quarantine = load_quarantine() if apply_quarantine else frozenset()
    accepted_scored = 0
    false_accepts = 0
    exact = 0
    quarantined = 0
    claims_touched = 0
    details: list[dict[str, Any]] = []

    for claim_id, row in merged_rows.items():
        if row.get("disposition") not in {"TRUE_STP", "HITL"}:
            continue
        truth = None
        for key in _claim_keys(claim_id):
            if key in gt:
                truth = gt[key]
                break
        if not truth:
            continue
        accepted = _accepted_values_from_row(row, claim_roots=roots)
        if not accepted:
            continue
        claims_touched += 1
        patient_for_same = accepted.get("patient_name")
        if patient_for_same is None and "patient_name" in truth:
            patient_for_same = truth["patient_name"].get("expected_value")
        for field, value in accepted.items():
            if critical_only and field not in _CRITICAL:
                continue
            if field not in truth:
                continue
            if apply_quarantine and _quarantined(claim_id, field, quarantine):
                quarantined += 1
                continue
            accepted_scored += 1
            expected = truth[field]["expected_value"]
            if exact_match(
                field, value, expected, patient_name=patient_for_same
            ):
                exact += 1
            else:
                false_accepts += 1
                details.append(
                    {
                        "claim_id": claim_id,
                        "field": field,
                        "predicted": value,
                        "truth": expected,
                        "confidence": truth[field].get("confidence"),
                    }
                )

    precision = (
        (accepted_scored - false_accepts) / accepted_scored if accepted_scored else None
    )
    return {
        "status": "SCORED",
        "gt_path": str(gt_path),
        "claims_scored": claims_touched,
        "accepted_fields_scored": accepted_scored,
        "false_accepts": false_accepts,
        "exact_matches": exact,
        "accepted_field_precision": round(precision, 6)
        if precision is not None
        else None,
        "baseline_false_accepts": 0,
        "false_accept_examples": details[:20],
        "gold_only": gold_only,
        "quarantine_applied": apply_quarantine,
        "quarantined_fields": quarantined,
    }
