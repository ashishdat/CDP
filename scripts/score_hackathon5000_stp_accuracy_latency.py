#!/usr/bin/env python3
"""Score Hackathon-5000 PRODUCT runs: STP, FA/accuracy vs shared GT, HITL latency.

Reads evaluation_results/<run>/results.jsonl (+ summary.json when present).
Writes docs/metrics/<run>/product_status.json and REPORT.md.

STP = true_stp / completed (never n - true_stp).
FA  = agent GT overlap; Hackathon-5000 vs M048* → NO_OVERLAP (not FA=0).
HITL latency = elapsed_sec on disposition==HITL rows (p50/p95/mean).

Usage:
  python3 -u scripts/score_hackathon5000_stp_accuracy_latency.py
  python3 -u scripts/score_hackathon5000_stp_accuracy_latency.py \\
      --run-dir evaluation_results/hackathon5000_all_v1 \\
      --metrics-dir docs/metrics/hackathon5000_all_v1 \\
      --target 5000
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_RUN = ROOT / "evaluation_results" / "hackathon5000_all_v1"
DEFAULT_METRICS = ROOT / "docs" / "metrics" / "hackathon5000_all_v1"


def _utc() -> str:
    return datetime.now(UTC).isoformat()


def _load_rows(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "results.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    # Dedup by claim_id / document keeping last write (resume-safe).
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("claim_id") or row.get("document") or row.get("doc") or "")
        if not key:
            continue
        by_id[key] = row
    return list(by_id.values())


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _latency_block(rows: list[dict[str, Any]], *, label: str) -> dict[str, Any]:
    vals = sorted(
        float(r["elapsed_sec"])
        for r in rows
        if isinstance(r.get("elapsed_sec"), (int, float))
    )
    return {
        "cohort": label,
        "n": len(vals),
        "mean_sec": round(statistics.fmean(vals), 3) if vals else None,
        "p50_sec": round(_percentile(vals, 0.50), 3) if vals else None,
        "p95_sec": round(_percentile(vals, 0.95), 3) if vals else None,
        "max_sec": round(vals[-1], 3) if vals else None,
        "min_sec": round(vals[0], 3) if vals else None,
    }


def _fa_block(run_dir: Path) -> dict[str, Any]:
    try:
        from packages.evaluation.agent_gt_paths import resolve_field_truth_path
        from scripts.score_hackathon_gt_accuracy import score as score_agent_gt

        gt_path = resolve_field_truth_path()
        if gt_path is None:
            return {
                "status": "GT_MISSING",
                "claims_scored": 0,
                "false_accepts": None,
                "accepted_field_precision": None,
                "note": "Shared field truth not found under docs/gt.",
            }
        gt = json.loads(gt_path.read_text(encoding="utf-8"))
        scored = score_agent_gt(run_dir, gt)
        status = scored.get("status") or (
            "NO_OVERLAP"
            if int(scored.get("claims_scored") or 0) == 0
            else "SCORED"
        )
        return {
            "status": status,
            "claims_scored": scored.get("claims_scored"),
            "false_accepts": scored.get("false_accepts"),
            "accepted_field_precision": scored.get("accepted_field_precision"),
            "exact_accuracy": scored.get("exact_accuracy"),
            "note": scored.get("note"),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "SCORE_FAILED",
            "claims_scored": 0,
            "false_accepts": None,
            "accepted_field_precision": None,
            "note": f"{type(exc).__name__}: {exc}",
        }


def score(
    run_dir: Path,
    *,
    target: int,
    metrics_dir: Path,
) -> dict[str, Any]:
    rows = _load_rows(run_dir)
    n = len(rows)
    by_disp = Counter(str(r.get("disposition") or "UNKNOWN") for r in rows)

    # Completed = CMS registration_ok completed ∨ unstructured REG recovery STP/HITL.
    def _unstructured_recovery(r: dict[str, Any]) -> bool:
        if r.get("hitl_track") == "UNSTRUCTURED_DI":
            return True
        meta = r.get("unstructured_reg") or r.get("unstructured_meta") or {}
        if isinstance(meta, dict) and meta.get("recovered"):
            return True
        reasons = r.get("reason_codes") or []
        return any("UNSTRUCTURED" in str(x) for x in reasons) and r.get(
            "disposition"
        ) in {"TRUE_STP", "HITL"}

    cms_completed = sum(
        1 for r in rows if r.get("completed") and r.get("registration_ok")
    )
    unstructured_completed = sum(
        1
        for r in rows
        if not r.get("registration_ok")
        and r.get("disposition") in {"TRUE_STP", "HITL"}
        and (
            r.get("hitl_track") == "UNSTRUCTURED_DI"
            or r.get("true_stp")
            or _unstructured_recovery(r)
        )
    )
    # Prefer cascade summary rollup when present (authoritative).
    summary_path = run_dir / "summary.json"
    summary: dict[str, Any] | None = None
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary = None

    if summary and isinstance(summary.get("completed"), int):
        completed = int(summary["completed"])
        true_stp = int(summary.get("true_stp") or 0)
        hitl = int(summary.get("hitl") or 0) + int(
            summary.get("unstructured_reg_hitl") or 0
        )
        # Prefer disposition HITL count for product_status parity with remainder.
        hitl = int(by_disp.get("HITL") or hitl)
        true_stp = int(by_disp.get("TRUE_STP") or true_stp)
        completed = true_stp + hitl
    else:
        true_stp = int(by_disp.get("TRUE_STP") or 0)
        hitl = int(by_disp.get("HITL") or 0)
        completed = true_stp + hitl
        if completed == 0:
            completed = cms_completed + unstructured_completed

    reg_failed = int(by_disp.get("REGISTRATION_FAILED") or 0)
    stp_pct = round(100.0 * true_stp / completed, 2) if completed else 0.0

    hitl_rows = [r for r in rows if r.get("disposition") == "HITL"]
    stp_rows = [r for r in rows if r.get("disposition") == "TRUE_STP"]
    hitl_tracks = Counter(str(r.get("hitl_track") or "UNKNOWN") for r in hitl_rows)
    blockers: Counter[str] = Counter()
    for r in hitl_rows:
        bl = r.get("critical_blockers") or []
        if not bl:
            blockers["(empty blockers)"] += 1
        for b in bl:
            blockers[str(b)] += 1
    reg_reasons: Counter[str] = Counter()
    for r in rows:
        if r.get("disposition") != "REGISTRATION_FAILED":
            continue
        reason = (
            r.get("registration_failure_reason")
            or r.get("failure_reason")
            or r.get("reg_reason")
            or "UNKNOWN"
        )
        reg_reasons[str(reason)] += 1

    agent_used = sum(1 for r in rows if r.get("agent_used"))
    fa = _fa_block(run_dir)

    latency = {
        "all_docs": _latency_block(rows, label="all"),
        "true_stp": _latency_block(stp_rows, label="TRUE_STP"),
        "hitl": _latency_block(hitl_rows, label="HITL"),
        "definition": "wall-clock elapsed_sec per document from cascade ledger",
    }

    remaining = max(0, target - n)
    run_status = "COMPLETE" if remaining == 0 and n >= target else (
        "COMPLETE" if summary and summary.get("run_status") == "COMPLETE" else "RUNNING"
    )
    if n == 0:
        run_status = "PENDING"

    manifest_path = run_dir / "run_manifest.json"
    profile = "PRODUCT"
    unstructured_first = True
    if manifest_path.is_file():
        try:
            man = json.loads(manifest_path.read_text(encoding="utf-8"))
            profile = str(man.get("profile") or profile)
            extra = man.get("extra") or {}
            uf = extra.get("unstructured_first") or man.get("unstructured_first")
            if uf is not None:
                unstructured_first = str(uf).strip() in {"1", "true", "True", "yes"}
        except json.JSONDecodeError:
            pass

    status = {
        "generated_at": _utc(),
        "run_dir": str(run_dir.relative_to(ROOT)) if run_dir.is_relative_to(ROOT) else str(run_dir),
        "profile": profile,
        "unstructured_first": unstructured_first,
        "n": n,
        "target": target,
        "remaining": remaining,
        "run_status": run_status,
        "disposition_counts": dict(by_disp),
        "completed": completed,
        "true_stp": true_stp,
        "stp_pct_of_completed": stp_pct,
        "hitl": hitl,
        "hitl_tracks": dict(hitl_tracks),
        "hitl_blockers": blockers.most_common(20),
        "registration_failed": reg_failed,
        "registration_reasons": reg_reasons.most_common(20),
        "agent_used_true": agent_used,
        "agent_used_rate_pct": round(100.0 * agent_used / n, 2) if n else 0.0,
        "vs_stp95": "PASS" if completed and stp_pct >= 95.0 else (
            "PENDING" if completed == 0 else "FAIL"
        ),
        "fa": {
            "status": fa.get("status"),
            "claims_scored": fa.get("claims_scored"),
            "false_accepts": fa.get("false_accepts"),
            "accepted_field_precision": fa.get("accepted_field_precision"),
            "exact_accuracy": fa.get("exact_accuracy"),
            "note": fa.get("note"),
        },
        "latency": latency,
        "summary_json_present": summary_path.is_file(),
    }

    metrics_dir.mkdir(parents=True, exist_ok=True)
    (metrics_dir / "product_status.json").write_text(
        json.dumps(status, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    fa_status = status["fa"]["status"]
    fa_fa = status["fa"]["false_accepts"]
    hitl_lat = latency["hitl"]
    all_lat = latency["all_docs"]
    report = f"""# Hackathon-5000 all-v1 PRODUCT

Generated: {status['generated_at']}

| Metric | Value |
|---|---|
| Docs | {n} / {target} ({run_status}) |
| TRUE_STP / completed | {true_stp} / {completed} (**{stp_pct}%**) |
| HITL | {hitl} ({dict(hitl_tracks)}) |
| REG | {reg_failed} |
| agent_used | {agent_used} ({status['agent_used_rate_pct']}%) |
| vs 95% STP | **{status['vs_stp95']}** |
| FA vs shared GT | **{fa_status}** (false_accepts={fa_fa}) |
| Latency all p50/p95 | {all_lat['p50_sec']}s / {all_lat['p95_sec']}s (n={all_lat['n']}) |
| Latency HITL p50/p95 | {hitl_lat['p50_sec']}s / {hitl_lat['p95_sec']}s (n={hitl_lat['n']}) |

Shared field truth: `docs/gt/hackathon_agent_field_truth.json` (M048*).
Hackathon-5000 is M046/M047* — expect **NO_OVERLAP**, not FA=0.
"""
    (metrics_dir / "REPORT.md").write_text(report, encoding="utf-8")
    return status


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    ap.add_argument("--metrics-dir", type=Path, default=DEFAULT_METRICS)
    ap.add_argument("--target", type=int, default=5000)
    args = ap.parse_args()
    status = score(args.run_dir, target=args.target, metrics_dir=args.metrics_dir)
    print(json.dumps(status, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
