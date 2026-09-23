#!/usr/bin/env python3
"""Summarize DI / HITL / local-OCR / VLM-token usage for a hackathon eval run."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


CRITICAL = {
    "total_charge",
    "total_charges",
    "patient_name",
    "insured_name",
    "insured_id_number",
    "patient_dob",
}


def _classify(engines: set[str]) -> tuple[bool, bool, bool]:
    has_di = any(
        "document_intelligence" in e
        or (e.startswith("azure") and "gpt" not in e and "4o" not in e)
        for e in engines
    )
    has_cloud = any(
        any(t in e for t in ("claude", "anthropic", "gpt4o", "gpt-4o", "conflict_agent"))
        for e in engines
    )
    has_local = any(any(t in e for t in ("paddle", "rapid", "tesseract")) for e in engines)
    return has_di, has_cloud, has_local


def _walk_engines(obj: Any, fmap: dict[str, set[str]]) -> None:
    if isinstance(obj, dict):
        fn = str(obj.get("field") or obj.get("field_name") or "")
        if fn:
            for c in obj.get("candidates") or []:
                if isinstance(c, dict) and c.get("engine"):
                    fmap[fn].add(str(c.get("engine")).casefold())
        for v in obj.values():
            _walk_engines(v, fmap)
    elif isinstance(obj, list):
        for v in obj:
            _walk_engines(v, fmap)


def summarize(run_dir: Path) -> dict[str, Any]:
    results_path = run_dir / "results.jsonl"
    rows = [
        json.loads(line)
        for line in results_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    n = len(rows)
    disp = Counter(r.get("disposition") for r in rows)
    stp = sum(1 for r in rows if r.get("true_stp"))
    hitl = [r for r in rows if r.get("disposition") == "HITL"]
    reg = [r for r in rows if r.get("disposition") == "REGISTRATION_FAILED"]

    meter_path = run_dir / "azure_di_meter.jsonl"
    meter: list[dict[str, Any]] = []
    if meter_path.exists():
        meter = [
            json.loads(line)
            for line in meter_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    di_by_kind = Counter(m.get("kind") for m in meter)
    di_by_field = Counter(m.get("field_name") for m in meter)
    di_ok = sum(1 for m in meter if m.get("ok"))

    token_path = run_dir / "vlm_token_meter.jsonl"
    token_rows: list[dict[str, Any]] = []
    if token_path.exists():
        token_rows = [
            json.loads(line)
            for line in token_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    tok_in = sum(int(r.get("input_tokens") or 0) for r in token_rows)
    tok_out = sum(int(r.get("output_tokens") or 0) for r in token_rows)
    tok_tot = sum(int(r.get("total_tokens") or 0) for r in token_rows)
    tok_by_provider: Counter[str] = Counter()
    for r in token_rows:
        prov = str(r.get("provider") or "unknown")
        tok_by_provider[prov] += int(r.get("total_tokens") or 0)

    field_present: Counter[str] = Counter()
    field_local_only: Counter[str] = Counter()
    field_had_di: Counter[str] = Counter()
    field_had_cloud: Counter[str] = Counter()
    di_charge_claims = 0
    claude_any_claims = 0
    local_only_critical = 0
    ca_calls = 0
    ca_claims = 0
    eng_attempted: Counter[str] = Counter()
    eng_observed: Counter[str] = Counter()

    for r in rows:
        cid = r["claim_id"]
        st = r.get("ocr_engine_stats") or {}
        for k, v in (st.get("engines_attempted") or {}).items():
            eng_attempted[k] += int(v) if isinstance(v, (int, float)) else 0
        for k, v in (st.get("engines_observed") or {}).items():
            eng_observed[k] += int(v) if isinstance(v, (int, float)) else 0

        fmap: dict[str, set[str]] = defaultdict(set)
        er_p = run_dir / "claims" / cid / "extract" / "ExtractionResult.json"
        if er_p.exists():
            _walk_engines(json.loads(er_p.read_text(encoding="utf-8")), fmap)

        claim_di = False
        claim_cloud = False
        for fn, engs in fmap.items():
            key = "total_charge" if fn == "total_charges" else fn
            if key not in CRITICAL:
                continue
            field_present[key] += 1
            has_di, has_cloud, has_local = _classify(engs)
            if has_di:
                field_had_di[key] += 1
                claim_di = True
            if has_cloud:
                field_had_cloud[key] += 1
                claim_cloud = True
            if has_local and not has_di and not has_cloud:
                field_local_only[key] += 1

        cengs = fmap.get("total_charge") or fmap.get("total_charges") or set()
        has_di, _, _ = _classify(cengs)
        if has_di:
            di_charge_claims += 1
        if claim_cloud:
            claude_any_claims += 1

        crit_fields = [
            f
            for f in fmap
            if ("total_charge" if f == "total_charges" else f) in CRITICAL
        ]
        if crit_fields and all(
            (not _classify(fmap[f])[0] and not _classify(fmap[f])[1]) for f in crit_fields
        ):
            local_only_critical += 1

        tel_p = run_dir / "claims" / cid / "ocr" / "ocr_telemetry.json"
        if tel_p.exists():
            tel = json.loads(tel_p.read_text(encoding="utf-8"))
            nca = 0
            for fa in tel.get("provider_attempts") or []:
                for a in fa.get("attempts") or []:
                    if "conflict" in str(a.get("engine") or "").casefold():
                        nca += 1
            if nca:
                ca_claims += 1
                ca_calls += nca

    blockers: Counter[str] = Counter()
    for r in hitl:
        bl = r.get("critical_blockers") or []
        if not bl:
            blockers["(empty blockers)"] += 1
        for b in bl:
            blockers[b] += 1

    elapsed = [float(r["elapsed_sec"]) for r in rows if isinstance(r.get("elapsed_sec"), (int, float))]
    elapsed_sorted = sorted(elapsed)
    median = (
        elapsed_sorted[len(elapsed_sorted) // 2] if elapsed_sorted else None
    )

    fields_out = []
    for f in [
        "total_charge",
        "patient_name",
        "insured_name",
        "insured_id_number",
        "patient_dob",
    ]:
        present = field_present[f]
        fields_out.append(
            {
                "field": f,
                "present": present,
                "local_only": field_local_only[f],
                "local_only_rate": (field_local_only[f] / present) if present else 0.0,
                "had_di": field_had_di[f],
                "had_cloud": field_had_cloud[f],
            }
        )

    return {
        "cohort": run_dir.name,
        "run_dir": str(run_dir),
        "n": n,
        "true_stp": stp,
        "true_stp_rate": (stp / n) if n else 0.0,
        "hitl": len(hitl),
        "hitl_rate": (len(hitl) / n) if n else 0.0,
        "registration_failed": len(reg),
        "dispositions": dict(disp),
        "median_elapsed_sec": median,
        "azure_di": {
            "api_calls": len(meter),
            "ok": di_ok,
            "fail": len(meter) - di_ok,
            "by_kind": dict(di_by_kind),
            "by_field": dict(di_by_field),
            "claims_with_di_charge": di_charge_claims,
            "claims_with_di_charge_rate": (di_charge_claims / n) if n else 0.0,
        },
        "vlm_tokens": {
            "metered": bool(token_rows),
            "calls": len(token_rows),
            "input_tokens": tok_in,
            "output_tokens": tok_out,
            "total_tokens": tok_tot,
            "by_provider_total_tokens": dict(tok_by_provider),
            "note": (
                None
                if token_rows
                else (
                    "LLM token usage was not persisted for this run. "
                    "Conflict-agent / crop-residual call counts are listed under cloud."
                )
            ),
        },
        "cloud": {
            "claims_with_claude_or_gpt_on_critical": claude_any_claims,
            "claims_with_claude_or_gpt_rate": (claude_any_claims / n) if n else 0.0,
            "conflict_agent_attempts": ca_calls,
            "conflict_agent_claims": ca_claims,
        },
        "local_ocr": {
            "claims_all_critical_local_only": local_only_critical,
            "claims_all_critical_local_only_rate": (local_only_critical / n) if n else 0.0,
            "fields": fields_out,
            "engine_attempts": dict(eng_attempted),
            "engine_observed": dict(eng_observed),
        },
        "hitl_blockers": dict(blockers),
        "hitl_claim_ids": [r.get("claim_id") or r.get("document") for r in hitl],
        "reg_claim_ids": [r.get("claim_id") or r.get("document") for r in reg],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    report = summarize(args.run_dir.resolve())
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
