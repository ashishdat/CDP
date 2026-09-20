#!/usr/bin/env python3
"""Bakeoff Claude Sonnet crop vision on remaining total_charge / name HITLs.

Uses Anthropic Messages API (POST /v1/messages) with crop-only evidence.
Reconstructs rectified CMS-1500 pages from saved geometry + zip when available;
falls back to OCR region crops from stored claim artifacts.
"""

from __future__ import annotations

import io
import json
import os
import time
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np
from PIL import Image

from packages.extraction_recovery.gpt4o_crop_residual import (
    _shape_charge,
    _shape_name,
)
from packages.settings import Settings
from packages.vlm_schema import VLMFieldRequest
from workers.vlm_fallback.factory import build_anthropic_claude_adapter

ROOT = Path("evaluation_results/hackathon_200_cascade_v12")
OVERLAY = Path("evaluation_results/hackathon_200_cascade_v12_remeasure_gap_audit_v3")
CLAIMS = ROOT / "claims"
OUT = Path("evaluation_results/claude_sonnet_hitl_crop_bakeoff_v1")

TARGET_GAPS = {
    ("total_charge", "CALIBRATION_HITL"),
    ("total_charge", "LINE_SUM_UNCORROBORATED"),
    ("patient_name", "EVIDENCE_POLICY_GAP"),
    ("patient_name", "NAME_ENGINE_CONFLICT"),
}


def _load_hitl_targets() -> list[dict]:
    by: dict[str, dict] = {}
    for line in (ROOT / "results.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            by[row["claim_id"]] = row
    if (OVERLAY / "results.jsonl").exists():
        for line in (OVERLAY / "results.jsonl").read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row["claim_id"] in by:
                by[row["claim_id"]].update(
                    {
                        k: row[k]
                        for k in (
                            "disposition",
                            "true_stp",
                            "gap_classes",
                            "critical_blockers",
                            "fields",
                            "document",
                        )
                        if k in row
                    }
                )
    targets = []
    for row in by.values():
        if row.get("disposition") != "HITL":
            continue
        for gap in row.get("gap_classes") or []:
            if not isinstance(gap, dict):
                continue
            key = (gap.get("field"), gap.get("gap_class"))
            if key in TARGET_GAPS:
                targets.append({**row, "_gap": gap})
                break
    return targets


def _warp_page(claim: Path, ocr: dict) -> Image.Image | None:
    app_dirs = list((claim / "application").glob("application-*"))
    if not app_dirs:
        return None
    app = app_dirs[0]
    geom_path = app / "GeometryResult.json"
    telem_path = app / "geometry_telemetry.json"
    if not geom_path.exists() or not telem_path.exists():
        return None
    geom = json.loads(geom_path.read_text())
    telem = json.loads(telem_path.read_text())
    src = telem.get("source") or {}
    archive = src.get("archive")
    entry = src.get("entry")
    if not archive or not entry or not Path(archive).exists():
        return None
    matrix = np.asarray(geom["source_to_geometry_transform"], dtype=float)
    # Prefer registration size; else OCR bbox extents.
    size = (2550, 3300)
    rr = app / "registration_report.json"
    if rr.exists():

        def walk(obj):
            if isinstance(obj, dict):
                if isinstance(obj.get("size"), (list, tuple)) and len(obj["size"]) == 2:
                    return int(obj["size"][0]), int(obj["size"][1])
                for value in obj.values():
                    found = walk(value)
                    if found:
                        return found
            elif isinstance(obj, list):
                for value in obj[:80]:
                    found = walk(value)
                    if found:
                        return found
            return None

        found = walk(json.loads(rr.read_text()))
        if found:
            size = found
    with ZipFile(archive) as zf:
        payload = zf.read(entry)
    with Image.open(io.BytesIO(payload)) as tiff:
        tiff.seek(int(geom["page_number"]) - 1)
        source = tiff.convert("L")
        pixels = cv2.warpPerspective(
            np.asarray(source), matrix, tuple(size), borderValue=255
        )
    return Image.fromarray(pixels).convert("RGB")


def _field_bbox(ocr: dict, field: str) -> tuple[int, int, int, int] | None:
    for row in ocr.get("fields") or []:
        if not isinstance(row, dict):
            continue
        if row.get("field") != field:
            continue
        bbox = tuple(row.get("ocr_region") or row.get("canonical_region") or ())
        if len(bbox) == 4:
            return tuple(int(v) for v in bbox)
    return None


def _crop_png(page: Image.Image, bbox: tuple[int, int, int, int]) -> bytes:
    x0, y0, x1, y1 = bbox
    pad = 8
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(page.width, x1 + pad), min(page.height, y1 + pad)
    crop = page.crop((x0, y0, x1, y1))
    if crop.width < 120 or crop.height < 40:
        scale = max(2, int(140 / max(crop.width, 1)))
        crop = crop.resize(
            (crop.width * scale, crop.height * scale), Image.Resampling.LANCZOS
        )
    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "crops").mkdir(exist_ok=True)
    settings = Settings()
    adapter = build_anthropic_claude_adapter(settings, timeout_seconds=90.0)
    print(
        f"claude bakeoff model={settings.anthropic_model} "
        f"endpoint={settings.anthropic_messages_endpoint}",
        flush=True,
    )

    targets = _load_hitl_targets()
    # Cap for cost control; full set still useful for names+charges.
    limit = int(os.environ.get("CDP_CLAUDE_BAKEOFF_LIMIT") or "40")
    targets = targets[:limit]
    print(f"targets={len(targets)}", flush=True)

    rows: list[dict] = []
    shaped = Counter()
    for index, row in enumerate(targets, 1):
        claim_id = row["claim_id"]
        gap = row["_gap"]
        field = gap["field"]
        claim = CLAIMS / claim_id
        ocr_path = claim / "ocr" / "OCRCandidates.json"
        if not ocr_path.exists():
            rows.append(
                {
                    "claim_id": claim_id,
                    "field": field,
                    "gap_class": gap.get("gap_class"),
                    "status": "OCR_MISSING",
                }
            )
            continue
        ocr = json.loads(ocr_path.read_text())
        page = _warp_page(claim, ocr)
        if page is None:
            rows.append(
                {
                    "claim_id": claim_id,
                    "field": field,
                    "gap_class": gap.get("gap_class"),
                    "status": "PAGE_UNAVAILABLE",
                }
            )
            continue
        bbox = _field_bbox(ocr, field)
        if bbox is None and field == "total_charge":
            # fallback canonical Box 28 band on CMS geometry
            bbox = (1045, 1825, 1248, 1875)
        if bbox is None:
            rows.append(
                {
                    "claim_id": claim_id,
                    "field": field,
                    "gap_class": gap.get("gap_class"),
                    "status": "BBOX_MISSING",
                }
            )
            continue

        png = _crop_png(page, bbox)
        crop_path = OUT / "crops" / f"{claim_id}__{field}.png"
        crop_path.write_bytes(png)

        priors: list[str] = []
        fo = next((f for f in ocr.get("fields") or [] if f.get("field") == field), {})
        for cand in fo.get("candidates") or []:
            if isinstance(cand, dict) and cand.get("value"):
                priors.append(str(cand["value"]))
        prior_value = ((row.get("fields") or {}).get(field) or {}).get("value")
        if prior_value:
            priors.insert(0, str(prior_value))

        field_type = "currency" if field == "total_charge" else "text"
        desc = (
            "Printed Box 28 total charge amount in dollars and cents"
            if field == "total_charge"
            else "Patient last name, first name, middle initial as printed/handwritten"
        )
        started = time.time()
        try:
            results = adapter.extract_fields(
                {field: png},
                [
                    VLMFieldRequest(
                        field_name=field,
                        field_type=field_type,
                        expected_description=desc,
                        prior_ocr_candidates=priors[:6],
                    )
                ],
            )
            item = results[0]
            raw = item.value
            if field == "total_charge":
                shaped_val, ok = _shape_charge(raw)
            else:
                shaped_val, ok = _shape_name(field, raw)
            elapsed = round(time.time() - started, 3)
            status = "SHAPED" if ok and not item.insufficient_evidence else (
                "ABSTAIN" if item.insufficient_evidence else "UNSHAPED"
            )
            shaped[f"{field}:{status}"] += 1
            out_row = {
                "claim_id": claim_id,
                "field": field,
                "gap_class": gap.get("gap_class"),
                "status": status,
                "raw_value": raw,
                "shaped_value": shaped_val if ok else None,
                "confidence": item.confidence,
                "insufficient_evidence": item.insufficient_evidence,
                "prior_value": prior_value,
                "priors": priors[:4],
                "elapsed_sec": elapsed,
                "usage": getattr(adapter, "last_usage", {}),
                "crop": str(crop_path),
            }
            rows.append(out_row)
            print(
                f"[{index}/{len(targets)}] {claim_id} {field} -> {status} "
                f"val={shaped_val or raw!r} prior={prior_value!r} {elapsed}s",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "claim_id": claim_id,
                    "field": field,
                    "gap_class": gap.get("gap_class"),
                    "status": "ERROR",
                    "error": f"{type(exc).__name__}: {exc}"[:400],
                }
            )
            print(f"[{index}/{len(targets)}] {claim_id} ERROR {exc}", flush=True)

    summary = {
        "model": settings.anthropic_model,
        "endpoint": settings.anthropic_messages_endpoint,
        "n": len(rows),
        "status_counts": dict(Counter(r.get("status") for r in rows)),
        "shaped_by_field": dict(shaped),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (OUT / "results.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=True) for r in rows) + "\n"
    )
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
