#!/usr/bin/env python3
"""Build agent field truth for Hackathon-5000 (M046*/M047*) via dual local OCR.

Hackathon ZIPs have no vendor labels. Shared docs/gt was M048* only (Hackathon-
1000), so 5000 runs scored NO_OVERLAP. This mines GOLD/SILVER labels from
RapidOCR + PaddleOCR full-page text + the same field heuristics used in
unstructured recovery — GOLD only when both engines agree after shaping.

Writes:
  docs/gt/hackathon5000_agent_field_truth.json
  (optional) merges into docs/gt/hackathon_agent_field_truth.json

Usage:
  python3 -u scripts/build_hackathon5000_agent_gt.py --sample 200 --seed 20261002
  python3 -u scripts/build_hackathon5000_agent_gt.py --sample 200 --merge-canonical
"""

from __future__ import annotations

import argparse
import contextlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from packages.extraction_recovery.field_cascade import semantic_accept  # noqa: E402
from packages.extraction_recovery.unstructured_reg_fallback import (  # noqa: E402
    _BAD_NAME,
    _heuristic_fields_from_di_text,
    _looks_like_person_name,
)
from scripts.score_hackathon_gt_accuracy import (  # noqa: E402
    CRITICAL,
    _canon_date,
    _canon_id,
    _canon_money,
    _canon_name,
)


def _normalize_key(field: str, value: str) -> str:
    if field in {"patient_dob", "date_of_birth"}:
        return _canon_date(value)
    if field in {"insured_id_number", "member_id"}:
        return _canon_id(value)
    if field in {"patient_name", "insured_name"}:
        return _canon_name(value)
    if field in {"total_charge", "total_charges"}:
        return _canon_money(value)
    return str(value or "").strip().upper()


def _display_for(field: str, value: str) -> str:
    if field in {"patient_dob", "date_of_birth"}:
        return _canon_date(value)
    if field in {"total_charge", "total_charges"}:
        return _canon_money(value)
    if field in {"insured_id_number", "member_id"}:
        return _canon_id(value)
    text = re.sub(r"[^A-Za-z0-9,.\- ]", " ", value or "")
    text = re.sub(r"\s+", " ", text).strip(" .,")
    return text.upper()


def merge_claims(*sources: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source in sources:
        for claim_id, payload in source.items():
            slot = merged.setdefault(
                claim_id,
                {
                    "document": payload.get("document"),
                    "fields": {},
                    "run_source": payload.get("run_source"),
                },
            )
            if payload.get("document"):
                slot["document"] = payload["document"]
            for field, meta in (payload.get("fields") or {}).items():
                slot["fields"][field] = meta
    return merged

DEFAULT_ZIP = ROOT / "data" / "Hackathon - 5000 Claims.zip"
DEFAULT_RUN = ROOT / "evaluation_results" / "hackathon5000_all_v1"
DEFAULT_OUT = ROOT / "docs" / "gt" / "hackathon5000_agent_field_truth.json"
CANONICAL = ROOT / "docs" / "gt" / "hackathon_agent_field_truth.json"


def _utc() -> str:
    return datetime.now(UTC).isoformat()


def _ocr_engines() -> tuple[Any, Any]:
    from rapidocr_onnxruntime import RapidOCR
    from paddleocr import PaddleOCR

    rapid = RapidOCR()
    paddle = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    return rapid, paddle


def _rapid_text(engine: Any, rgb) -> str:
    result, _ = engine(rgb)
    lines: list[str] = []
    for item in result or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            text = str(item[1] or "").strip()
            if text:
                lines.append(text)
    return "\n".join(lines)


def _paddle_text(engine: Any, rgb) -> str:
    raw = engine.ocr(rgb, cls=True)
    lines: list[str] = []
    for block in raw or []:
        for item in block or []:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                payload = item[1]
                text = str(
                    payload[0] if isinstance(payload, (list, tuple)) else payload
                ).strip()
                if text:
                    lines.append(text)
    return "\n".join(lines)


def _shaped_fields(text: str) -> dict[str, str]:
    raw = _heuristic_fields_from_di_text(text)
    out: dict[str, str] = {}
    for field, value in (raw or {}).items():
        if field not in CRITICAL:
            continue
        ok, _ = semantic_accept(field, value)
        if ok and str(value or "").strip():
            out[field] = str(value).strip()
    return out


def _paddle_usable(field: str, value: str | None) -> bool:
    """Drop form-junk paddle reads (e.g. 'NAME, FISST N') before consensus."""
    if not value or not str(value).strip():
        return False
    text = str(value).strip()
    if field in {"patient_name", "insured_name"}:
        if _BAD_NAME.search(text) or not _looks_like_person_name(text):
            return False
        # Common NUCC placeholder OCR.
        if re.search(r"\bFISST\b|\bFIRST\s*N(?:AME)?\b|\bNAME,\s*F", text, re.I):
            return False
    if field == "patient_dob":
        # Paddle often latches onto printed example dates on the form shell.
        pass
    return True


def _label_fields(
    rapid_fields: dict[str, str], paddle_fields: dict[str, str]
) -> dict[str, dict[str, Any]]:
    field_gt: dict[str, dict[str, Any]] = {}
    for field in CRITICAL:
        r = rapid_fields.get(field)
        p = paddle_fields.get(field) if _paddle_usable(field, paddle_fields.get(field)) else None
        if r and p:
            if _normalize_key(field, r) == _normalize_key(field, p):
                field_gt[field] = {
                    "expected_value": _display_for(field, r),
                    "source": "multi_engine_consensus:paddleocr+rapidocr",
                    "confidence": "GOLD",
                }
                continue
            # Disagree on real ink — abstain (do not invent).
            continue
        # Rapid is the production unstructured-first engine; prefer it for SILVER.
        if r:
            field_gt[field] = {
                "expected_value": _display_for(field, r),
                "source": "single_engine_shaped:rapidocr",
                "confidence": "SILVER",
            }
        elif p:
            field_gt[field] = {
                "expected_value": _display_for(field, p),
                "source": "single_engine_shaped:paddleocr",
                "confidence": "SILVER",
            }
    return field_gt


def _load_completed_docs(run_dir: Path) -> list[dict[str, Any]]:
    ledger = run_dir / "results.jsonl"
    rows: list[dict[str, Any]] = []
    if not ledger.is_file():
        return rows
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("disposition") in {"TRUE_STP", "HITL"} and row.get("document"):
            rows.append(row)
    # Dedup last-write
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        by_id[str(row.get("claim_id") or row["document"])] = row
    return list(by_id.values())


def _stratified_sample(
    rows: list[dict[str, Any]], *, n: int, seed: int
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_group[str(row.get("group_id") or "UNK")].append(row)
    # Force-include all HITL (scarce, high value for FA).
    hitl = [r for r in rows if r.get("disposition") == "HITL"]
    chosen: dict[str, dict[str, Any]] = {
        str(r.get("claim_id") or r["document"]): r for r in hitl
    }
    remaining = max(0, n - len(chosen))
    # Proportional TRUE_STP by group.
    stp_by_group = {
        g: [r for r in items if r.get("disposition") == "TRUE_STP"]
        for g, items in by_group.items()
    }
    total_stp = sum(len(v) for v in stp_by_group.values()) or 1
    alloc = {
        g: max(1, round(remaining * len(items) / total_stp)) if items else 0
        for g, items in stp_by_group.items()
    }
    # Fix rounding to exact remaining.
    while sum(alloc.values()) > remaining:
        g = max(alloc, key=alloc.get)
        if alloc[g] > 0:
            alloc[g] -= 1
    while sum(alloc.values()) < remaining:
        g = max(stp_by_group, key=lambda k: len(stp_by_group[k]))
        alloc[g] = alloc.get(g, 0) + 1
    for g, k in alloc.items():
        pool = list(stp_by_group.get(g) or [])
        rng.shuffle(pool)
        for row in pool[:k]:
            chosen[str(row.get("claim_id") or row["document"])] = row
    out = list(chosen.values())
    rng.shuffle(out)
    return out[:n] if len(out) > n else out


def build_labels(
    *,
    zip_path: Path,
    docs: list[str],
    resume_claims: dict[str, dict[str, Any]] | None = None,
    checkpoint: Path | None = None,
) -> dict[str, dict[str, Any]]:
    import numpy as np

    claims: dict[str, dict[str, Any]] = dict(resume_claims or {})
    pending = [d for d in docs if d.replace("/", "__") not in claims]
    print(f"pending={len(pending)} already={len(claims)}", flush=True)
    if not pending:
        return claims
    rapid, paddle = _ocr_engines()
    print("ocr engines ready", flush=True)
    with ZipFile(zip_path) as zf:
        for i, document in enumerate(pending, start=1):
            claim_id = document.replace("/", "__")
            try:
                img = Image.open(BytesIO(zf.read(document))).convert("RGB")
            except Exception as exc:  # noqa: BLE001
                print(f"skip {document}: {type(exc).__name__}: {exc}", flush=True)
                continue
            rgb = np.asarray(img)
            try:
                try:
                    r_text = _rapid_text(rapid, rgb)
                    p_text = _paddle_text(paddle, rgb)
                except Exception as exc:  # noqa: BLE001
                    print(f"ocr_fail {document}: {type(exc).__name__}: {exc}", flush=True)
                    continue
            finally:
                with contextlib.suppress(Exception):
                    img.close()
            field_gt = _label_fields(_shaped_fields(r_text), _shaped_fields(p_text))
            if not field_gt:
                print(f"[{i}/{len(pending)}] {document} no labels", flush=True)
                continue
            claims[claim_id] = {
                "document": document,
                "fields": field_gt,
                "run_source": "hackathon5000_dual_local_ocr",
            }
            gold = sum(1 for m in field_gt.values() if m.get("confidence") == "GOLD")
            print(
                f"[{i}/{len(pending)}] {document} fields={len(field_gt)} gold={gold}",
                flush=True,
            )
            if checkpoint is not None and (i % 10 == 0 or i == len(pending)):
                write_gt(
                    checkpoint,
                    claims,
                    dataset="Hackathon - 5000 Claims.zip",
                )
    return claims


def write_gt(path: Path, claims: dict[str, dict[str, Any]], *, dataset: str) -> dict[str, Any]:
    conf = Counter()
    field_n = Counter()
    for payload in claims.values():
        for field, meta in (payload.get("fields") or {}).items():
            conf[str(meta.get("confidence") or "?")] += 1
            field_n[field] += 1
    payload = {
        "dataset": dataset,
        "created_by": "agent_consensus_gt_hackathon5000_v1",
        "created_at": _utc(),
        "methodology": [
            "No vendor labels on Hackathon-5000 ZIP — agent-created GT.",
            "Full-page RapidOCR + PaddleOCR text independently.",
            "Field heuristics + semantic_accept (same shaping as unstructured REG).",
            "GOLD: both engines agree after normalize/shape.",
            "SILVER: single engine shaped; abstain on engine conflicts.",
            "Never invent DOB/amounts/IDs when engines disagree or ink is empty.",
        ],
        "stats": {
            "claims": len(claims),
            "field_labels": sum(field_n.values()),
            "by_confidence": dict(conf),
            "by_field": dict(field_n),
        },
        "claims": claims,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    ap.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--sample", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20261002)
    ap.add_argument(
        "--merge-canonical",
        action="store_true",
        help="Merge 5000 labels into docs/gt/hackathon_agent_field_truth.json "
        "(keeps existing M048* labels).",
    )
    ap.add_argument(
        "--documents-file",
        type=Path,
        default=None,
        help="Optional explicit document list (skips stratified sample).",
    )
    args = ap.parse_args()

    zip_path = args.zip if args.zip.is_absolute() else ROOT / args.zip
    run_dir = args.run_dir if args.run_dir.is_absolute() else ROOT / args.run_dir
    out = args.out if args.out.is_absolute() else ROOT / args.out
    assert zip_path.is_file(), zip_path

    if args.documents_file:
        docs = [
            ln.strip().replace("\\", "/")
            for ln in Path(args.documents_file).read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
    else:
        rows = _load_completed_docs(run_dir)
        sample = _stratified_sample(rows, n=args.sample, seed=args.seed)
        docs = [str(r["document"]).replace("\\", "/") for r in sample]
        print(
            f"sampled {len(docs)} from {len(rows)} completed "
            f"(seed={args.seed} hitl={sum(1 for r in sample if r.get('disposition')=='HITL')})",
            flush=True,
        )

    resume: dict[str, dict[str, Any]] = {}
    if out.is_file():
        try:
            prev = json.loads(out.read_text(encoding="utf-8"))
            resume = dict(prev.get("claims") or {})
            print(f"resume from {out} claims={len(resume)}", flush=True)
        except json.JSONDecodeError:
            resume = {}
    claims = build_labels(
        zip_path=zip_path,
        docs=docs,
        resume_claims=resume,
        checkpoint=out,
    )
    gt = write_gt(out, claims, dataset="Hackathon - 5000 Claims.zip")
    print(json.dumps({"out": str(out), "stats": gt["stats"]}, indent=2), flush=True)

    if args.merge_canonical and CANONICAL.is_file():
        existing = json.loads(CANONICAL.read_text(encoding="utf-8"))
        merged = merge_claims(existing.get("claims") or {}, claims)
        # Preserve M048 methodology notes + append 5000 notes.
        conf = Counter()
        field_n = Counter()
        for payload in merged.values():
            for field, meta in (payload.get("fields") or {}).items():
                conf[str(meta.get("confidence") or "?")] += 1
                field_n[field] += 1
        combined = {
            "dataset": "Hackathon-1000 + Hackathon-5000 (agent field truth)",
            "created_by": "agent_consensus_gt_merged_v1",
            "created_at": _utc(),
            "methodology": list(existing.get("methodology") or [])
            + [
                "Hackathon-5000 (M046*/M047*): dual local OCR Rapid+Paddle consensus.",
                "GOLD on 5000 requires both engines agree; SILVER is single-engine.",
            ],
            "stats": {
                "claims": len(merged),
                "field_labels": sum(field_n.values()),
                "by_confidence": dict(conf),
                "by_field": dict(field_n),
                "hackathon1000_claims": len(existing.get("claims") or {}),
                "hackathon5000_claims": len(claims),
            },
            "claims": merged,
        }
        CANONICAL.write_text(json.dumps(combined, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {"canonical": str(CANONICAL), "stats": combined["stats"]}, indent=2
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
