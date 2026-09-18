#!/usr/bin/env python3
"""Bakeoff gpt-4o crop vision on hard-150 FIELD_INK DOB/ID HITL failures.

Reconstructs rectified CMS-1500 pages from saved geometry + zip, crops the
failing DOB/ID ROIs, and asks Azure gpt-4o (crop-only) to read them.
Compares against prior cascade / TrOCR / Azure DI residual outputs.
"""
from __future__ import annotations

import io
import json
import os
import re
import time
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np
from PIL import Image

from packages.extraction_recovery.dob_azure_di_residual import (
    _normalize_dob_text,
    _shape_dob_text,
)
from packages.settings import Settings
from workers.vlm_fallback.adapter import AzureOpenAIVisionAdapter
from workers.vlm_fallback.schema import VLMFieldRequest

ROOT = Path("evaluation_results/hackathon_150_blind_hard_cascade_v12_3m")
CLAIMS = ROOT / "claims"
OUT = Path("evaluation_results/dob_id_hitl_vlm_bakeoff_v12_3m")


def shape_dob(text: str | None) -> str | None:
    raw = _normalize_dob_text(text)
    if not raw:
        return None
    try:
        shaped, ok = _shape_dob_text("patient_dob", raw)
    except (ValueError, TypeError, AttributeError):
        shaped, ok = None, False
    if ok and shaped:
        return shaped
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", raw)
    if not m:
        return None
    mm, dd, yy = m.groups()
    if len(yy) == 2:
        yy = ("19" if int(yy) > 30 else "20") + yy
    return f"{int(mm):02d}/{int(dd):02d}/{yy}"

def shape_id(text: str | None) -> str | None:
    t = re.sub(r"\s+", "", (text or "").strip().upper())
    if not t or t in {"ID", "MEMBER", "INSURED", "PATIENT", "NONE", "N/A"}:
        return None
    alnum = re.sub(r"[^A-Z0-9]", "", t)
    if len(alnum) < 5 or not re.search(r"\d", alnum):
        return None
    return alnum


def warp_size(app: Path, ocr: dict) -> tuple[int, int]:
    rr = app / "registration_report.json"
    if rr.exists():

        def walk(o):
            if isinstance(o, dict):
                if isinstance(o.get("size"), (list, tuple)) and len(o["size"]) == 2:
                    return int(o["size"][0]), int(o["size"][1])
                for v in o.values():
                    got = walk(v)
                    if got:
                        return got
            elif isinstance(o, list):
                for v in o[:80]:
                    got = walk(v)
                    if got:
                        return got
            return None

        found = walk(json.loads(rr.read_text()))
        if found:
            return found
    max_x = max_y = 0
    for f in ocr.get("fields") or []:
        for key in ("ocr_region", "canonical_region"):
            b = f.get(key)
            if b and len(b) == 4:
                max_x = max(max_x, int(b[2]))
                max_y = max(max_y, int(b[3]))
    if max_x > 1000 and max_y > 1000:
        return max_x + 50, max_y + 50
    return 2550, 3300


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "crops").mkdir(exist_ok=True)

    settings = Settings()
    adapter = AzureOpenAIVisionAdapter(
        endpoint=settings.azure_openai_endpoint or os.environ["AZURE_OPENAI_ENDPOINT"],
        deployment=settings.azure_ai_evaluation_deployment
        or os.environ.get("AZURE_AI_EVALUATION_DEPLOYMENT", "gpt-4o"),
        api_version=settings.azure_openai_api_version
        or os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        api_key=settings.azure_openai_api_key or os.environ["AZURE_OPENAI_API_KEY"],
        enabled=True,
        timeout_seconds=60.0,
    )

    rows = [
        json.loads(line)
        for line in (ROOT / "results.jsonl").read_text().splitlines()
        if line.strip()
    ]
    hitl = [
        r
        for r in rows
        if r.get("hitl_track") == "FIELD_INK"
        and r.get("registration_ok")
        and any(
            b in (r.get("critical_blockers") or [])
            for b in ("patient_dob", "insured_id_number")
        )
    ]
    print(f"bakeoff targets: {len(hitl)}", flush=True)

    results: list[dict] = []
    for r in hitl:
        doc = r["document"]
        safe = doc.replace("/", "__")
        claim = CLAIMS / safe
        app_dirs = list((claim / "application").glob("application-*"))
        if not app_dirs:
            print("NO_APP", doc, flush=True)
            continue
        app = app_dirs[0]
        geom = json.loads((app / "GeometryResult.json").read_text())
        telem = json.loads((app / "geometry_telemetry.json").read_text())
        ocr = json.loads((claim / "ocr" / "OCRCandidates.json").read_text())
        matrix = np.asarray(geom["source_to_geometry_transform"], dtype=float)
        size = warp_size(app, ocr)

        src = telem["source"]
        with ZipFile(src["archive"]) as zf:
            payload = zf.read(src["entry"])
        with Image.open(io.BytesIO(payload)) as tiff:
            tiff.seek(int(geom["page_number"]) - 1)
            source = tiff.convert("L")
            pixels = cv2.warpPerspective(
                np.asarray(source), matrix, tuple(size), borderValue=255
            )
        page = Image.fromarray(pixels).convert("RGB")

        blockers = r.get("critical_blockers") or []
        fields_to_try = [
            f for f in ("patient_dob", "insured_id_number") if f in blockers
        ]
        crops_png: dict[str, bytes] = {}
        requests: list[VLMFieldRequest] = []
        baseline: dict[str, dict] = {}

        for field in fields_to_try:
            fo = next((f for f in ocr["fields"] if f.get("field") == field), None)
            if not fo:
                continue
            bbox = tuple(fo.get("ocr_region") or fo.get("canonical_region") or ())
            if len(bbox) != 4:
                continue
            x0, y0, x1, y1 = map(int, bbox)
            pad = 10
            x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
            x1, y1 = min(page.width, x1 + pad), min(page.height, y1 + pad)
            crop = page.crop((x0, y0, x1, y1))
            if crop.width < 120 or crop.height < 40:
                scale = max(2, int(140 / max(crop.width, 1)))
                crop = crop.resize(
                    (crop.width * scale, crop.height * scale),
                    Image.Resampling.LANCZOS,
                )
            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            png = buf.getvalue()
            crops_png[field] = png
            crop.save(OUT / "crops" / f"{safe}__{field}.png")

            cands = [(c.get("engine"), c.get("text")) for c in (fo.get("candidates") or [])]
            cascade = fo.get("cascade") or {}
            cascade_value = None
            for step in cascade.get("steps") or []:
                if step.get("accepted"):
                    cascade_value = step.get("selected_value")
                    break
            if cascade_value is None and (cascade.get("steps") or []):
                cascade_value = cascade["steps"][-1].get("selected_value")
            baseline[field] = {
                "bbox": [x0, y0, x1, y1],
                "cascade_accepted": cascade.get("accepted"),
                "cascade_value": cascade_value,
                "candidates": cands,
                "trocr": fo.get("trocr_residual"),
                "azure_di": fo.get("azure_di_residual"),
            }
            prior = [
                str(t)
                for _, t in cands
                if t
            ]
            if field == "patient_dob":
                desc = (
                    "Handwritten CMS-1500 box 3 patient date of birth. "
                    "Return MM/DD/YYYY when clearly readable; abstain if empty or illegible."
                )
                ftype = "date"
            else:
                desc = (
                    "Handwritten or typed CMS-1500 box 1a insured/member ID. "
                    "Alphanumeric ID only — not phone, NPI, EIN, or printed labels."
                )
                ftype = "code"
            requests.append(
                VLMFieldRequest(
                    field_name=field,
                    field_type=ftype,
                    expected_description=desc,
                    prior_ocr_candidates=prior[:6],
                )
            )

        if not requests:
            continue

        t0 = time.time()
        err = None
        try:
            vlm = adapter.extract_fields(crops_png, requests)
        except Exception as exc:  # noqa: BLE001 — bakeoff must continue
            vlm = []
            err = f"{type(exc).__name__}: {exc}"
        elapsed = time.time() - t0
        vlm_by = {v.field_name: v for v in vlm}

        row: dict = {
            "document": doc,
            "blockers": blockers,
            "elapsed_sec": round(elapsed, 2),
            "error": err,
            "usage": getattr(adapter, "last_usage", {}),
            "warp_size": list(size),
            "fields": {},
        }
        for field in fields_to_try:
            v = vlm_by.get(field)
            raw = None if not v else v.value
            insuff = None if not v else v.insufficient_evidence
            conf = None if not v else v.confidence
            shaped = shape_dob(raw) if field == "patient_dob" else shape_id(raw)
            row["fields"][field] = {
                "vlm_raw": raw,
                "vlm_insufficient": insuff,
                "vlm_confidence": conf,
                "vlm_shaped": shaped,
                "promising": bool(shaped) and not insuff,
                "baseline": baseline.get(field),
            }
        results.append(row)
        preview = {
            f: row["fields"][f].get("vlm_shaped") or row["fields"][f].get("vlm_raw")
            for f in row["fields"]
        }
        print(doc, preview, "err", err, f"{elapsed:.1f}s", flush=True)

    (OUT / "results.json").write_text(json.dumps(results, indent=2, default=str) + "\n")
    n_dob = sum(1 for r in results if "patient_dob" in r["fields"])
    n_id = sum(1 for r in results if "insured_id_number" in r["fields"])
    prom_dob = sum(
        1 for r in results if r["fields"].get("patient_dob", {}).get("promising")
    )
    prom_id = sum(
        1
        for r in results
        if r["fields"].get("insured_id_number", {}).get("promising")
    )
    summary = {
        "docs": len(results),
        "dob": {"n": n_dob, "promising_shaped": prom_dob},
        "id": {"n": n_id, "promising_shaped": prom_id},
        "errors": sum(1 for r in results if r.get("error")),
        "mean_vlm_sec": round(
            sum(r["elapsed_sec"] for r in results) / max(len(results), 1), 2
        ),
        "dob_abstain": sum(
            1
            for r in results
            if r["fields"].get("patient_dob", {}).get("vlm_insufficient")
        ),
        "id_abstain": sum(
            1
            for r in results
            if r["fields"].get("insured_id_number", {}).get("vlm_insufficient")
        ),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("SUMMARY", json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
