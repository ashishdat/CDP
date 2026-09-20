#!/usr/bin/env python3
"""Remasure remaining HITL using existing OCR field evidence + configured Claude.

Prior decision-only remasures reused paddle/rapid OCRCandidates but never injected
the configured Anthropic Claude crop residual into those fields. This path:

  1. Builds the current overlay HITL set (base + prior remasures).
  2. Reuses existing OCRCandidates (field evidence already paid for).
  3. Injects Claude shaped values from the bakeoff ledger when present, else
     calls Claude live with those OCR priors (CDP_CROP_VLM_PROVIDER=claude).
  4. Re-runs rank → validate → assemble → complete (decision path).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_hackathon_1000_cascade import (  # noqa: E402
    _claim_slug,
    _run_stage,
    _summarize_final,
    _utc_now,
    _write_json,
)

BASE = ROOT / "evaluation_results" / "hackathon_200_cascade_v12"
# Newest remasures first so overlay + OCR reuse Claude line inject and prior
# total-charge selector flips (do not fall back to pre-Claude OCR).
REMEASURE_PREFER = [
    ROOT
    / "evaluation_results"
    / "hackathon_200_cascade_v12_remeasure_dual_vision_v9",
    ROOT
    / "evaluation_results"
    / "hackathon_200_cascade_v12_remeasure_dual_vision_v8",
    ROOT
    / "evaluation_results"
    / "hackathon_200_cascade_v12_remeasure_dual_vision_v7",
    ROOT
    / "evaluation_results"
    / "hackathon_200_cascade_v12_remeasure_dual_vision_v6",
    ROOT
    / "evaluation_results"
    / "hackathon_200_cascade_v12_remeasure_dual_vision_v5",
    ROOT
    / "evaluation_results"
    / "hackathon_200_cascade_v12_remeasure_dual_vision_v4",
    ROOT
    / "evaluation_results"
    / "hackathon_200_cascade_v12_remeasure_charge_selector_v3",
    ROOT
    / "evaluation_results"
    / "hackathon_200_cascade_v12_remeasure_claude_charge_e2e_v2",
    ROOT
    / "evaluation_results"
    / "hackathon_200_cascade_v12_remeasure_claude_charge_e2e_v1",
    ROOT
    / "evaluation_results"
    / "hackathon_200_cascade_v12_remeasure_claude_evidence_v1",
    ROOT / "evaluation_results" / "hackathon_200_cascade_v12_remeasure_gap_audit_v3",
    ROOT / "evaluation_results" / "hackathon_200_cascade_v12_remeasure_defer_fix_v2",
    ROOT / "evaluation_results" / "hackathon_200_cascade_v12_remeasure_hitl",
    BASE,
]
BAKEOFF = (
    ROOT / "evaluation_results" / "claude_sonnet_hitl_crop_bakeoff_v1" / "results.jsonl"
)
DEFAULT_OUT = (
    ROOT
    / "evaluation_results"
    / "hackathon_200_cascade_v12_remeasure_dual_vision_v9"
)

_VISION_FIELDS = frozenset(
    {"total_charge", "total_charges", "patient_name", "insured_id_number", "patient_dob"}
)


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _load_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return rows
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rows[row["claim_id"]] = row
    return rows


def _overlay_rows() -> dict[str, dict[str, Any]]:
    rows = _load_jsonl(BASE / "results.jsonl")
    for rem in reversed(REMEASURE_PREFER[:-1]):
        rows.update(_load_jsonl(rem / "results.jsonl"))
    return rows


def _best_claim_dir(claim_id: str) -> Path | None:
    for rem in REMEASURE_PREFER:
        claim = rem / "claims" / claim_id
        if (claim / "ocr" / "OCRCandidates.json").is_file():
            return claim
    return None


def _load_bakeoff() -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if not BAKEOFF.is_file():
        return out
    for line in BAKEOFF.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("status") != "SHAPED" or not row.get("shaped_value"):
            continue
        out[(row["claim_id"], row["field"])] = row
    return out


def _claude_candidate(
    *,
    value: str,
    raw_value: str | None,
    confidence: float | None,
    bbox: list[int] | tuple[int, ...],
    image_width: int,
    image_height: int,
    reason: str,
) -> dict[str, Any]:
    conf = float(confidence) if confidence is not None else 0.9
    x0, y0, x1, y1 = (int(v) for v in bbox)
    return {
        "value": value,
        "raw_value": raw_value or value,
        "engine": "anthropic_claude_crop",
        "model_name": "claude-sonnet-4-6",
        "model_version": "anthropic-messages",
        "preprocessing_variant": "claude_crop_residual",
        "preprocessing_version": "cascade-v12-claude-remeasure",
        "raw_confidence": conf,
        "calibrated_confidence": conf,
        "confidence": conf,
        "reason_code": reason,
        "validation_results": ["ANTHROPIC_CLAUDE_CROP", reason],
        "shadow_review_only": False,
        "latency_ms": 0.0,
        "bounding_box": {
            "x0": float(x0),
            "y0": float(y0),
            "x1": float(x1),
            "y1": float(y1),
            "image_width": float(image_width),
            "image_height": float(image_height),
        },
        "bbox": [x0, y0, x1, y1],
        "image_width": float(image_width),
        "image_height": float(image_height),
        "reason": reason,
        "independence_group": "anthropic_claude_crop_residual",
    }


def _field_bbox(field: dict[str, Any]) -> list[int] | None:
    for key in ("ocr_region", "canonical_region"):
        region = field.get(key)
        if isinstance(region, (list, tuple)) and len(region) == 4:
            return [int(v) for v in region]
    return None


def _page_image(ocr: dict[str, Any], claim_dir: Path | None = None):
    """Reconstruct rectified page the same way as Claude bakeoff (zip + warp)."""
    from PIL import Image

    # Prefer explicit paths when present.
    geom_ref = ocr.get("geometry_reference")
    if geom_ref:
        geom_path = Path(geom_ref)
        if not geom_path.is_file():
            geom_path = ROOT / geom_ref
        if geom_path.is_file():
            geom = json.loads(geom_path.read_text())
            for key in ("page_image", "warped_page", "image_path", "rectified_page"):
                page_path = geom.get(key)
                if page_path and Path(page_path).is_file():
                    return Image.open(page_path).convert("RGB")
                if page_path and (ROOT / page_path).is_file():
                    return Image.open(ROOT / page_path).convert("RGB")

    if claim_dir is None:
        return None
    try:
        import io

        import cv2
        import numpy as np
        from zipfile import ZipFile
    except ImportError:
        return None

    app_dirs = list((claim_dir / "application").glob("application-*"))
    if not app_dirs:
        # Remasure copies may omit application/ — fall back to base run claim.
        claim_id = claim_dir.name
        base_claim = BASE / "claims" / claim_id
        app_dirs = list((base_claim / "application").glob("application-*"))
        if app_dirs:
            claim_dir = base_claim
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


def _live_claude(
    *,
    field_name: str,
    image,
    bbox: list[int],
    priors: list[str],
) -> dict[str, Any] | None:
    from packages.extraction_recovery.gpt4o_crop_residual import (
        residual_candidate_dict,
        run_gpt4o_crop_residual,
    )

    # Provider selected via CDP_CROP_VLM_PROVIDER / ANTHROPIC_CROP_RESIDUAL_ENABLED.
    result = run_gpt4o_crop_residual(
        image=image,
        bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        field_name=field_name,
        prior_candidates=priors[:6],
    )
    if not result.attempted or not result.shaped or not result.value:
        return None
    if result.insufficient_evidence:
        return None
    cand = residual_candidate_dict(
        result,
        bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        image_size=(image.width, image.height),
    )
    if cand is None:
        return None
    cand["shadow_review_only"] = False
    cand["independence_group"] = "anthropic_claude_crop_residual"
    return cand


def _line_bbox(line: dict[str, Any]) -> list[int] | None:
    for key in ("canonical_region", "ocr_region", "charge_region", "bbox"):
        region = line.get(key)
        if isinstance(region, (list, tuple)) and len(region) == 4:
            return [int(v) for v in region]
    for cand in line.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        bb = cand.get("bounding_box") or cand.get("bbox")
        if isinstance(bb, dict) and bb.get("x0") is not None:
            return [int(bb["x0"]), int(bb["y0"]), int(bb["x1"]), int(bb["y1"])]
        if isinstance(bb, (list, tuple)) and len(bb) >= 4:
            return [int(v) for v in bb[:4]]
    return None


def _line_needs_vision(line: dict[str, Any]) -> bool:
    """True when line lacks usable vision+local consensus on the selected charge.

    Presence of a gpt4o/Claude candidate is not enough — place-shift rivals often
    leave the selected amount uncorroborated. Only skip when consensus already holds.
    """
    try:
        from packages.claim_evidence.line_sum_authority import (
            line_has_gpt4o_local_consensus,
        )
    except Exception:  # noqa: BLE001
        return True
    try:
        return not line_has_gpt4o_local_consensus(line)
    except Exception:  # noqa: BLE001
        return True


def _inject_claude_into_ocr(
    ocr: dict[str, Any],
    *,
    claim_id: str,
    gap_fields: list[str],
    bakeoff: dict[tuple[str, str], dict[str, Any]],
    allow_live: bool,
    claim_dir: Path | None = None,
) -> dict[str, Any]:
    """Mutate OCR in place: Claude on blocking headers + charge service lines."""
    telemetry: dict[str, Any] = {
        "injected": [],
        "skipped": [],
        "live": [],
        "bakeoff": [],
        "service_lines": [],
    }
    page = None
    image_width = image_height = 0

    def _ensure_page():
        nonlocal page, image_width, image_height
        if page is not None:
            return page
        page = _page_image(ocr, claim_dir=claim_dir)
        if page is not None:
            image_width, image_height = page.size
        return page

    for field in ocr.get("fields") or []:
        name = str(field.get("field") or "")
        if name not in gap_fields or name not in _VISION_FIELDS:
            continue
        bbox = _field_bbox(field) or [0, 0, 1, 1]
        priors = [
            str(c.get("value") or "").strip()
            for c in (field.get("candidates") or [])
            if isinstance(c, dict) and (c.get("value") or "").strip()
        ]
        kept = [
            c
            for c in (field.get("candidates") or [])
            if isinstance(c, dict)
            and "claude" not in str(c.get("engine") or "").casefold()
            and "anthropic" not in str(c.get("engine") or "").casefold()
        ]
        field["candidates"] = kept

        bake = bakeoff.get((claim_id, name))
        cand = None
        source = None
        if bake and bake.get("shaped_value"):
            if not image_width:
                for prior in kept:
                    bb = prior.get("bounding_box") or {}
                    if bb.get("image_width"):
                        image_width = int(bb["image_width"])
                        image_height = int(bb["image_height"])
                        break
            if not image_width:
                image_width, image_height = 1712, 2214
            cand = _claude_candidate(
                value=str(bake["shaped_value"]),
                raw_value=str(bake.get("raw_value") or bake["shaped_value"]),
                confidence=bake.get("confidence"),
                bbox=bbox,
                image_width=image_width,
                image_height=image_height,
                reason="CLAUDE_BAKEOFF_FIELD_EVIDENCE",
            )
            source = "bakeoff"
        elif allow_live:
            if _ensure_page() is None:
                telemetry["skipped"].append({"field": name, "reason": "PAGE_UNAVAILABLE"})
                continue
            cand = _live_claude(
                field_name=name, image=page, bbox=bbox, priors=priors
            )
            source = "live"
            if cand is None:
                telemetry["skipped"].append({"field": name, "reason": "CLAUDE_ABSTAIN"})
                continue
        if cand is None:
            telemetry["skipped"].append({"field": name, "reason": "NO_CLAUDE_VALUE"})
            continue

        field["candidates"] = [cand, *kept]
        field["gpt4o_crop_residual"] = {
            "attempted": True,
            "configured": True,
            "review_only": False,
            "shaped": True,
            "insufficient_evidence": False,
            "reason": cand.get("reason") or "CLAUDE_CROP",
            "value": cand.get("value"),
            "confidence": cand.get("confidence"),
            "engine": "anthropic_claude_crop",
            "provider": "claude",
            "source": source,
        }
        attempts = list(field.get("attempts") or [])
        attempts.append(
            {
                "engine": "anthropic_claude_crop",
                "reason": cand.get("reason") or "CLAUDE_INJECTED",
                "observation": {"text": cand.get("raw_value") or cand.get("value")},
            }
        )
        field["attempts"] = attempts
        telemetry["injected"].append(
            {"field": name, "value": cand.get("value"), "source": source}
        )
        telemetry[source].append(name)

    charge_blocked = any(f in {"total_charge", "total_charges"} for f in gap_fields)
    if charge_blocked and allow_live:
        max_lines = int(os.environ.get("CDP_CLAUDE_LINE_MAX") or "4")
        touched = 0
        for index, line in enumerate(ocr.get("service_lines") or []):
            if touched >= max_lines:
                break
            if not isinstance(line, dict) or not _line_needs_vision(line):
                continue
            bbox = _line_bbox(line)
            if bbox is None:
                telemetry["skipped"].append(
                    {"field": f"service_line[{index}]", "reason": "BBOX_MISSING"}
                )
                continue
            if _ensure_page() is None:
                telemetry["skipped"].append(
                    {"field": f"service_line[{index}]", "reason": "PAGE_UNAVAILABLE"}
                )
                break
            priors = [
                str(c.get("value") or c.get("raw_value") or "").strip()
                for c in (line.get("candidates") or [])
                if isinstance(c, dict)
                and (c.get("value") or c.get("raw_value") or "").strip()
            ]
            if line.get("charges"):
                priors.insert(0, str(line.get("charges")))
            kept = [
                c
                for c in (line.get("candidates") or [])
                if isinstance(c, dict)
                and "claude" not in str(c.get("engine") or "").casefold()
                and "anthropic" not in str(c.get("engine") or "").casefold()
            ]
            cand = _live_claude(
                field_name="charges", image=page, bbox=bbox, priors=priors[:6]
            )
            if cand is None:
                telemetry["skipped"].append(
                    {"field": f"service_line[{index}]", "reason": "CLAUDE_ABSTAIN"}
                )
                continue
            line["candidates"] = [cand, *kept]
            if cand.get("value") and not str(line.get("charges") or "").strip():
                line["charges"] = cand["value"]
                line["charge_amount"] = cand["value"]
            line["gpt4o_crop_residual"] = {
                "attempted": True,
                "configured": True,
                "review_only": False,
                "shaped": True,
                "value": cand.get("value"),
                "engine": "anthropic_claude_crop",
                "source": "live_line",
            }
            attempts = list(line.get("attempts") or [])
            attempts.append(
                {
                    "engine": "anthropic_claude_crop",
                    "reason": "CLAUDE_LINE_CHARGE_INJECTED",
                    "observation": {"text": cand.get("raw_value") or cand.get("value")},
                }
            )
            line["attempts"] = attempts
            telemetry["service_lines"].append(
                {"line_index": index, "value": cand.get("value"), "source": "live"}
            )
            telemetry["injected"].append(
                {
                    "field": f"service_line[{index}].charges",
                    "value": cand.get("value"),
                    "source": "live",
                }
            )
            telemetry["live"].append(f"service_line[{index}]")
            touched += 1

    return telemetry



def _process_one(
    *,
    document: str,
    prior_row: dict[str, Any],
    out_dir: Path,
    bakeoff: dict[tuple[str, str], dict[str, Any]],
    allow_live: bool,
    decision_only: bool = False,
) -> dict[str, Any]:
    claim_id = _claim_slug(document)
    src_claim = _best_claim_dir(claim_id)
    claim_out = out_dir / "claims" / claim_id
    if claim_out.exists():
        shutil.rmtree(claim_out)
    claim_out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    logs = claim_out / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    reprocess_tag = (
        "dual_vision_decision_only_v4"
        if decision_only
        else "claude_field_evidence_v1"
    )

    if src_claim is None:
        row = {
            "finished": True,
            "claim_id": claim_id,
            "document": document,
            "disposition": "OCR_MISSING",
            "true_stp": False,
            "prior_disposition": prior_row.get("disposition"),
            "elapsed_sec": round(time.time() - started, 3),
            "ts": _utc_now(),
            "reprocess": reprocess_tag,
        }
        _write_json(claim_out / "result.json", row)
        return row

    ocr_dir = claim_out / "ocr"
    ocr_dir.mkdir(parents=True, exist_ok=True)
    ocr = json.loads((src_claim / "ocr" / "OCRCandidates.json").read_text())
    gap_fields = sorted(
        {
            g.get("field")
            for g in (prior_row.get("gap_classes") or [])
            if isinstance(g, dict) and g.get("field")
        }
        | set(prior_row.get("critical_blockers") or [])
    )
    if decision_only:
        # Preserve Claude/gpt4o already on lines from e2e remasure; re-run
        # rank→complete so LineChargeSelector dual-vision / defer-Box28 fixes apply.
        inject_tel = {
            "injected": [],
            "skipped": [],
            "live": [],
            "bakeoff": [],
            "service_lines": [],
            "decision_only": True,
            "src_claim": str(src_claim),
            "preserved_claude": sum(
                1
                for line in (ocr.get("service_lines") or [])
                if isinstance(line, dict)
                for c in (line.get("candidates") or [])
                if isinstance(c, dict)
                and (
                    "claude" in str(c.get("engine") or "").casefold()
                    or "anthropic" in str(c.get("engine") or "").casefold()
                )
            ),
        }
        src_inject = src_claim / "ocr" / "claude_inject_telemetry.json"
        if src_inject.is_file():
            try:
                inject_tel["prior_inject"] = json.loads(src_inject.read_text())
            except Exception:  # noqa: BLE001
                pass
    else:
        inject_tel = _inject_claude_into_ocr(
            ocr,
            claim_id=claim_id,
            gap_fields=[f for f in gap_fields if f in _VISION_FIELDS],
            bakeoff=bakeoff,
            allow_live=allow_live,
            claim_dir=src_claim,
        )
    (ocr_dir / "OCRCandidates.json").write_text(json.dumps(ocr, indent=2))
    _write_json(ocr_dir / "claude_inject_telemetry.json", inject_tel)
    src_tel = src_claim / "ocr" / "ocr_telemetry.json"
    if src_tel.exists():
        shutil.copy2(src_tel, ocr_dir / "ocr_telemetry.json")

    stages = [
        (
            "rank",
            [
                sys.executable,
                "-m",
                "scripts.rank_from_ocr",
                str(ocr_dir / "OCRCandidates.json"),
                str(claim_out / "rank"),
            ],
        ),
        (
            "validate",
            [
                sys.executable,
                "-m",
                "scripts.validate_from_ranked",
                str(claim_out / "rank" / "RankedCandidates.json"),
                str(claim_out / "validate"),
                "--template-id",
                "cms1500",
                "--template-version",
                "02-12",
            ],
        ),
        (
            "assemble",
            [
                sys.executable,
                "-m",
                "scripts.assemble_extraction_result",
                str(ocr_dir / "OCRCandidates.json"),
                str(claim_out / "rank" / "RankedCandidates.json"),
                str(claim_out / "validate" / "ValidationResults.json"),
                str(claim_out / "extract"),
            ],
        ),
        (
            "complete",
            [
                sys.executable,
                "-m",
                "scripts.complete_from_extraction",
                str(claim_out / "extract" / "ExtractionResult.json"),
                str(claim_out / "final"),
                "--document-family",
                "CMS1500",
            ],
        ),
    ]
    for stage_name, cmd in stages:
        rc, tail = _run_stage(cmd, logs / f"{stage_name}.log")
        if rc != 0:
            row = {
                "finished": True,
                "claim_id": claim_id,
                "document": document,
                "registration_ok": True,
                "completed": False,
                "true_stp": False,
                "disposition": "STAGE_FAILURE",
                "failed_stage": stage_name,
                "error": tail[-500:],
                "claude_inject": inject_tel,
                "prior_disposition": prior_row.get("disposition"),
                "prior_true_stp": prior_row.get("true_stp"),
                "prior_blockers": prior_row.get("critical_blockers"),
                "elapsed_sec": round(time.time() - started, 3),
                "ts": _utc_now(),
                "reprocess": reprocess_tag,
            }
            _write_json(claim_out / "result.json", row)
            return row

    summary = _summarize_final(claim_out)
    row = {
        "finished": True,
        "claim_id": claim_id,
        "document": document,
        "registration_ok": True,
        "completed": summary["completed"],
        "true_stp": summary["true_stp"],
        "review_required": summary["review_required"],
        "disposition": "TRUE_STP" if summary["true_stp"] else "HITL",
        "critical_blockers": summary.get("critical_blockers"),
        "gap_classes": summary.get("gap_classes"),
        "fields": summary.get("fields"),
        "service_line_charges": summary.get("service_line_charges"),
        "claude_inject": inject_tel,
        "prior_disposition": prior_row.get("disposition"),
        "prior_true_stp": prior_row.get("true_stp"),
        "prior_blockers": prior_row.get("critical_blockers"),
        "elapsed_sec": round(time.time() - started, 3),
        "ts": _utc_now(),
        "reprocess": reprocess_tag,
    }
    _write_json(claim_out / "result.json", row)
    return row


def main() -> int:
    _load_dotenv()
    # Ensure Claude is the crop residual provider for any live calls.
    os.environ.setdefault("CDP_CROP_VLM_PROVIDER", "claude")
    os.environ.setdefault("ANTHROPIC_CROP_RESIDUAL_ENABLED", "true")
    os.environ.setdefault("CDP_GPT4O_CROP_RESIDUAL", "1")
    os.environ.setdefault("CDP_GPT4O_CROP_ACCEPT", "1")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call Claude live when bakeoff row missing (uses ANTHROPIC_API_KEY).",
    )
    parser.add_argument(
        "--no-live",
        action="store_true",
        help="Bakeoff-only inject (default when --live not set is bakeoff+live).",
    )
    parser.add_argument(
        "--decision-only",
        action="store_true",
        help=(
            "Reuse OCR (incl. Claude line inject) as-is; re-run rank→complete so "
            "dual-vision LineChargeSelector and Box28 defer fixes apply."
        ),
    )
    args = parser.parse_args()
    decision_only = bool(args.decision_only)
    allow_live = False if decision_only else (bool(args.live) or not bool(args.no_live))

    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    ledger = out_dir / "results.jsonl"

    overlay = _overlay_rows()
    prior_by_doc = {row["document"]: row for row in overlay.values()}
    bakeoff = {} if decision_only else _load_bakeoff()
    targets = sorted(
        doc for doc, row in prior_by_doc.items() if row.get("disposition") == "HITL"
    )
    if args.limit and args.limit > 0:
        targets = targets[: args.limit]

    print(
        f"claude_field_evidence targets={len(targets)} bakeoff={len(bakeoff)} "
        f"live={allow_live} decision_only={decision_only} workers={args.workers}",
        flush=True,
    )

    lock = threading.Lock()
    rows: list[dict[str, Any]] = []
    flipped = 0

    def _one(doc: str) -> dict[str, Any]:
        return _process_one(
            document=doc,
            prior_row=prior_by_doc[doc],
            out_dir=out_dir,
            bakeoff=bakeoff,
            allow_live=allow_live,
            decision_only=decision_only,
        )

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(_one, doc): doc for doc in targets}
        for fut in as_completed(futures):
            row = fut.result()
            with lock:
                rows.append(row)
                with ledger.open("a") as fh:
                    fh.write(json.dumps(row) + "\n")
                if row.get("disposition") == "TRUE_STP" and not row.get("prior_true_stp"):
                    flipped += 1
                print(
                    f"{row.get('claim_id')} {row.get('prior_disposition')}->"
                    f"{row.get('disposition')} blockers={row.get('critical_blockers')} "
                    f"inject={row.get('claude_inject', {}).get('injected')}",
                    flush=True,
                )

    # Projected overlay STP
    merged = dict(overlay)
    for row in rows:
        merged[row["claim_id"]] = row
    stp = sum(1 for r in merged.values() if r.get("disposition") == "TRUE_STP")
    hitl = sum(1 for r in merged.values() if r.get("disposition") == "HITL")
    completed = sum(1 for r in merged.values() if r.get("completed"))
    rem_hitl = sum(1 for r in rows if r.get("disposition") == "HITL")
    rem_stp = sum(1 for r in rows if r.get("disposition") == "TRUE_STP")
    gap_pareto: dict[str, int] = {}
    for r in merged.values():
        if r.get("disposition") != "HITL":
            continue
        for g in r.get("gap_classes") or []:
            if isinstance(g, dict):
                key = f"{g.get('field')}:{g.get('gap_class')}"
                gap_pareto[key] = gap_pareto.get(key, 0) + 1
    summary = {
        "n_remeasured": len(rows),
        "flipped_count": flipped,
        "flipped_to_stp": sorted(
            r["claim_id"]
            for r in rows
            if r.get("disposition") == "TRUE_STP" and not r.get("prior_true_stp")
        ),
        "remeasure_stp": rem_stp,
        "remeasure_hitl": rem_hitl,
        "projected_completed": completed,
        "projected_stp": stp,
        "projected_hitl": hitl,
        "projected_stp_rate": round(stp / completed, 4) if completed else 0.0,
        "remaining_gaps": dict(
            sorted(gap_pareto.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        "bakeoff_rows": len(bakeoff),
        "live_enabled": allow_live,
        "decision_only": decision_only,
        "fix": (
            "dual_vision_decision_only_reuse_claude_ocr"
            if decision_only
            else "claude_inject_into_existing_field_evidence"
        ),
        "generated_at": _utc_now(),
    }
    _write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
