#!/usr/bin/env python3
"""Fast REG recovery: DI page-read only (no CMS registration / OCR pools).

For known REGISTRATION_FAILED docs, template geometry already failed. Re-running
the full cascade is slow and wasteful. This path:
  1. load page from hackathon zip
  2. Azure DI full-page read + heuristic field shaping
  3. promote to TRUE_STP / HITL / keep REG (same rules as cascade v12.3m)

Usage:
  python3 -u scripts/rerun_unstructured_reg_fast.py \\
    --out-dir evaluation_results/hackathon_400_remainder_independent_v13c \\
    --docs-file /tmp/reg_retry_docs_400.txt
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_ZIP = ROOT / "data" / "Hackathon - 1000 Claims.zip"
REQUIRED = {"patient_name", "patient_dob", "insured_id_number", "total_charge"}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _claim_id(document: str) -> str:
    return document.replace("/", "__").replace("\\", "__")


def _group_id(document: str) -> str:
    return document.split("/", 1)[0] if "/" in document else "unknown"


def _load_docs(args: argparse.Namespace) -> list[str]:
    docs: list[str] = []
    if args.docs_file:
        raw = Path(args.docs_file).read_text(encoding="utf-8").strip()
        docs.extend(p.strip().replace("\\", "/") for p in raw.split(",") if p.strip())
    if args.documents:
        docs.extend(
            p.strip().replace("\\", "/")
            for p in str(args.documents).split(",")
            if p.strip()
        )
    # de-dupe preserve order
    return list(dict.fromkeys(docs))


def _append(ledger: Path, row: dict) -> None:
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--docs-file", type=Path, default=None)
    parser.add_argument("--documents", default="")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    # Force heuristics-only (no gpt-4o agent 401 latency).
    os.environ["CDP_UNSTRUCTURED_REG_FALLBACK"] = "1"
    os.environ["CDP_UNSTRUCTURED_REG_AGENT"] = "0"

    # Composition root: DI read engine factory (same as cascade).
    from workers.ocr_engine_factories import wire_package_ocr_providers

    wire_package_ocr_providers()

    from packages.extraction_recovery.unstructured_reg_fallback import (
        run_unstructured_reg_fallback,
    )
    from PIL import Image

    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    claims = out_dir / "claims"
    claims.mkdir(parents=True, exist_ok=True)
    ledger = out_dir / "results.jsonl"
    progress = out_dir / "progress_reg_fast.txt"

    docs = _load_docs(args)
    if args.limit and args.limit > 0:
        docs = docs[: args.limit]
    if not docs:
        print("ERROR: no documents", flush=True)
        return 2
    if not args.zip.exists():
        print(f"ERROR: zip missing {args.zip}", flush=True)
        return 2

    print(
        f"fast_reg_start n={len(docs)} agent=0 out={out_dir} ts={_utc()}",
        flush=True,
    )
    counts = {"TRUE_STP": 0, "HITL": 0, "REGISTRATION_FAILED": 0, "ERROR": 0}

    with ZipFile(args.zip) as zf:
        names = set(zf.namelist())
        for i, document in enumerate(docs, 1):
            started = time.time()
            claim_id = _claim_id(document)
            claim_out = claims / claim_id
            claim_out.mkdir(parents=True, exist_ok=True)
            disposition = "REGISTRATION_FAILED"
            unstructured_meta = None
            error = None
            try:
                # zip members may omit or include slight path variants
                key = document if document in names else next(
                    (n for n in names if n.replace("\\", "/").endswith(document.split("/")[-1])
                     and n.replace("\\", "/").startswith(document.split("/")[0])),
                    None,
                )
                if key is None:
                    raise FileNotFoundError(f"not in zip: {document}")
                page = Image.open(BytesIO(zf.read(key))).convert("RGB")
                try:
                    fb = run_unstructured_reg_fallback(page)
                finally:
                    page.close()
                unstructured_meta = {
                    "attempted": fb.attempted,
                    "reason": fb.reason,
                    "agent_used": fb.agent_used,
                    "fields": dict(fb.fields),
                }
                if REQUIRED.issubset(fb.fields):
                    disposition = "TRUE_STP"
                elif fb.fields:
                    disposition = "HITL"
            except Exception as exc:  # noqa: BLE001
                disposition = "ERROR"
                error = f"{type(exc).__name__}: {exc}"[:500]

            unstructured_hitl = disposition == "HITL" and bool(
                (unstructured_meta or {}).get("fields")
            )
            row = {
                "finished": True,
                "claim_id": claim_id,
                "document": document,
                "bundle_id": document.rsplit(".", 1)[0] if "." in document else document,
                "group_id": _group_id(document),
                "registration_ok": False,
                "allows_cms_geometry": False,
                "completed": disposition in {"TRUE_STP", "HITL"},
                "true_stp": disposition == "TRUE_STP",
                "disposition": disposition,
                "registration_reason": "FAST_UNSTRUCTURED_REG_RETRY",
                "hitl_track": "UNSTRUCTURED_DI" if unstructured_hitl else None,
                "critical_blockers": (
                    [f for f in sorted(REQUIRED) if f not in (unstructured_meta or {}).get("fields", {})]
                    if unstructured_hitl
                    else None
                ),
                "unstructured_reg_fallback": unstructured_meta,
                "error": error,
                "elapsed_sec": round(time.time() - started, 3),
                "ts": _utc(),
                "strategy_id": "unstructured-reg-fast-v1",
            }
            (claim_out / "result.json").write_text(
                json.dumps(row, indent=2) + "\n", encoding="utf-8"
            )
            _append(ledger, row)
            counts[disposition] = counts.get(disposition, 0) + 1
            msg = (
                f"progress {i}/{len(docs)} {claim_id} disp={disposition} "
                f"sec={row['elapsed_sec']} fields={list(((unstructured_meta or {}).get('fields') or {}).keys())}"
            )
            print(msg, flush=True)
            progress.write_text(msg + "\n" + _utc() + "\n", encoding="utf-8")

    summary = {
        "mode": "unstructured-reg-fast-v1",
        "n": len(docs),
        "counts": counts,
        "generated_at": _utc(),
    }
    (out_dir / "reg_fast_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(f"fast_reg_done {json.dumps(summary)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
