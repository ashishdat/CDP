"""Unstructured fallback when CMS-1500 template registration fails.

Hard blind REG is not always "bad geometry on a CMS-1500". Some pages are
freeform handwritten claim notes with **no form grid** (e.g. HJHO.015). SIFT /
LightGlue / DI page-corners cannot invent a template warp for those pages.

Stack for this path (cost-gated, never common path):
1. Azure DI prebuilt-read on the full page → observed ink text
2. Optional Azure OpenAI gpt-4o **text** JSON extract of critical fields from
   that DI text (not a geometry agent; not full-page vision by default)
3. Deterministic ``semantic_accept`` / span shaping before any STP accept

A vision geometry agent is the wrong tool here — there is no form to align.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from PIL import Image

from packages.extraction_recovery.field_cascade import semantic_accept
from packages.extraction_recovery.span_selection import select_field_span

_CRITICAL = (
    "patient_name",
    "insured_name",
    "patient_dob",
    "insured_id_number",
    "total_charge",
)

_build_azure_review_adapter: Callable[[Any], Any] | None = None


def configure_azure_review_adapter_factory(factory: Callable[[Any], Any]) -> None:
    """Composition root injects Azure review VLM adapter construction."""
    global _build_azure_review_adapter
    _build_azure_review_adapter = factory


@dataclass(frozen=True)
class UnstructuredRegFallbackResult:
    attempted: bool
    configured: bool
    reason: str
    di_text: str | None = None
    fields: dict[str, str] = field(default_factory=dict)
    field_reasons: dict[str, str] = field(default_factory=dict)
    agent_used: bool = False


def unstructured_reg_fallback_enabled() -> bool:
    raw = (os.environ.get("CDP_UNSTRUCTURED_REG_FALLBACK") or "1").strip().casefold()
    return raw not in {"0", "false", "no", "off"}


def _agent_enabled() -> bool:
    raw = (os.environ.get("CDP_UNSTRUCTURED_REG_AGENT") or "1").strip().casefold()
    return raw not in {"0", "false", "no", "off"}


def _shape_field(field_name: str, raw: str | None) -> tuple[str | None, str]:
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not text:
        return None, "EMPTY"
    datatype = {
        "patient_name": "PERSON_NAME",
        "insured_name": "PERSON_NAME",
        "patient_dob": "DATE",
        "insured_id_number": "ALPHANUMERIC_ID",
        "total_charge": "CURRENCY",
    }.get(field_name, "")
    span = select_field_span(text, datatype, field_name)
    selected = re.sub(r"\s+", " ", str(span.selected_text or text)).strip()
    ok, reason = semantic_accept(field_name, selected)
    if ok:
        return selected, f"SHAPED:{reason}"
    return None, f"UNSHAPED:{reason}"


def _heuristic_fields_from_di_text(di_text: str) -> dict[str, str]:
    """Cheap first pass: line-oriented heuristics before calling the agent."""
    out: dict[str, str] = {}
    lines = [ln.strip() for ln in di_text.splitlines() if ln.strip()]
    for ln in lines[:40]:
        if re.fullmatch(r"\d{1,2}[\s/.\-]\d{1,2}[\s/.\-]\d{2,4}", ln):
            shaped, reason = _shape_field("patient_dob", ln)
            if shaped and "FUTURE" not in reason:
                year = re.findall(r"\d{4}", shaped)
                if year and int(year[-1]) <= 2015:
                    out["patient_dob"] = shaped
                    break
                if not year:
                    out.setdefault("patient_dob", shaped)
    id_candidates: list[str] = []
    for ln in lines:
        # Skip provider/tax lines; still mine mixed identity lines that mention city.
        if re.search(r"\bnpi\b|\btax\b|buford|martin,?\s*inc|\bhealthcare\b", ln, re.IGNORECASE):
            continue
        for tok in re.findall(r"\b\d{7,12}\b", ln):
            if len(tok) == 10 and (tok.startswith("1") or tok[0] in "234567"):
                continue
            if len(tok) == 9 and tok.startswith("58"):
                continue
            if len(tok) == 7:  # truncated EIN / noise
                continue
            shaped, _ = _shape_field("insured_id_number", tok)
            if shaped:
                id_candidates.append(shaped)
    if id_candidates:
        id_candidates.sort(key=lambda v: (abs(len(re.sub(r"\D", "", v)) - 9), len(v)))
        out["insured_id_number"] = id_candidates[0]
    for ln in lines[:25]:
        if "," in ln and re.search(r"[A-Za-z]{2,}", ln):
            if re.search(r"united|healthcare|martin|buford|npi|cpt", ln, re.IGNORECASE):
                continue
            shaped, _ = _shape_field("patient_name", ln)
            if shaped:
                out.setdefault("patient_name", shaped)
                out.setdefault("insured_name", shaped)
                break
    for ln in lines:
        if re.search(r"\bF\d{2}", ln, re.IGNORECASE):
            continue
        for m in re.finditer(r"\$(\d{2,5}\.\d{2})\b|(\b\d{2,4}\.00\b)", ln):
            raw = m.group(1) or m.group(2)
            shaped, _ = _shape_field("total_charge", raw)
            if shaped:
                out.setdefault("total_charge", shaped)
                break
        if "total_charge" in out:
            break
    return out


def _agent_should_run(fields: dict[str, str]) -> bool:
    if not _agent_enabled():
        return False
    if "patient_dob" not in fields or "patient_name" not in fields:
        return True
    if "insured_id_number" not in fields or "total_charge" not in fields:
        return True
    id_digits = re.sub(r"\D", "", fields.get("insured_id_number") or "")
    # Phone (10) or truncated EIN fragments (7) are suspicious — ask the agent.
    if len(id_digits) in {7, 10} or not (8 <= len(id_digits) <= 12):
        return True
    charge = fields.get("total_charge") or ""
    return bool(re.fullmatch(r"\$?\d{1,2}\.\d{2}", charge))


def _agent_fields_from_di_text(di_text: str, *, settings: Any | None = None) -> dict[str, str]:
    """gpt-4o text JSON extract from DI ink (no geometry, no invented pixels)."""
    try:
        from packages.settings import get_settings
    except ImportError:
        return {}
    if _build_azure_review_adapter is None:
        return {}
    cfg = settings or get_settings()
    if not getattr(cfg, "azure_ai_evaluation_enabled", False):
        return {}
    try:
        adapter = _build_azure_review_adapter(cfg)
    except (OSError, ValueError, RuntimeError, TypeError, AttributeError, KeyError):
        return {}

    prompt = (
        "Extract CMS-1500 critical claim fields from the OCR text of a medical "
        "claim page that may be freeform (not a filled form grid). "
        "Return strict JSON with keys: patient_name, insured_name, patient_dob, "
        "insured_id_number, total_charge. Use null when not clearly present. "
        "Do not invent values. Dates as MM/DD/YYYY when possible. "
        "insured_id_number is the subscriber/member id (not phone, NPI, or tax id). "
        "total_charge is the claim total (not a diagnosis code).\n\nOCR text:\n"
        f"{di_text[:6000]}"
    )
    client = getattr(adapter, "_client", None)
    endpoint = getattr(adapter, "_endpoint", None)
    deployment = getattr(adapter, "_deployment", None) or getattr(
        cfg, "azure_ai_evaluation_deployment", None
    )
    api_version = getattr(cfg, "azure_openai_api_version", None) or "2024-10-21"
    if client is None or not endpoint or not deployment:
        return {}
    url = (
        f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions"
        f"?api-version={api_version}"
    )
    payload = {
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": "You extract claim fields. Reply with JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    try:
        response = client.post(url, json=payload)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except Exception:  # noqa: BLE001 — 401/timeout/parse must not crash REG path
        return {}
    out: dict[str, str] = {}
    if not isinstance(parsed, dict):
        return out
    for key in _CRITICAL:
        raw = parsed.get(key)
        if raw is None:
            continue
        shaped, _ = _shape_field(key, str(raw))
        if shaped:
            out[key] = shaped
    return out


def run_unstructured_reg_fallback(
    image: Image.Image,
    *,
    settings: Any | None = None,
) -> UnstructuredRegFallbackResult:
    """Full-page DI (+ optional text agent) after template registration fails."""
    if not unstructured_reg_fallback_enabled():
        return UnstructuredRegFallbackResult(
            attempted=False,
            configured=False,
            reason="UNSTRUCTURED_REG_FALLBACK_DISABLED",
        )
    try:
        from packages.azure_di_contracts import (
            azure_document_intelligence_configured,
            build_azure_read_engine,
        )
        from packages.recovery.azure_di_meter import record_azure_di_call
        from packages.settings import get_settings
    except Exception as exc:  # noqa: BLE001
        return UnstructuredRegFallbackResult(
            attempted=False,
            configured=False,
            reason=f"IMPORT_ERROR:{type(exc).__name__}",
        )
    cfg = settings or get_settings()
    if not azure_document_intelligence_configured(cfg):
        return UnstructuredRegFallbackResult(
            attempted=False,
            configured=False,
            reason="AZURE_DI_NOT_CONFIGURED",
        )
    try:
        engine = build_azure_read_engine(cfg)
        backend = getattr(engine, "_backend", None)
        if backend is None or not hasattr(backend, "analyze_raw"):
            return UnstructuredRegFallbackResult(
                attempted=False,
                configured=True,
                reason="AZURE_DI_BACKEND_NO_RAW",
            )
        stream = BytesIO()
        image.convert("RGB").save(stream, format="PNG")
        payload = backend.analyze_raw(stream.getvalue())
        record_azure_di_call(kind="other", ok=True, detail="UNSTRUCTURED_REG_PAGE_READ")
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(Exception):
            record_azure_di_call(
                kind="other",
                ok=False,
                detail=f"UNSTRUCTURED_REG_ERROR:{type(exc).__name__}",
            )
        return UnstructuredRegFallbackResult(
            attempted=True,
            configured=True,
            reason=f"AZURE_DI_ERROR:{type(exc).__name__}:{str(exc)[:120]}",
        )

    di_text = str((payload.get("analyzeResult") or {}).get("content") or "").strip()
    if not di_text:
        return UnstructuredRegFallbackResult(
            attempted=True,
            configured=True,
            reason="AZURE_DI_EMPTY_CONTENT",
            di_text=None,
        )

    fields = _heuristic_fields_from_di_text(di_text)
    agent_used = False
    if _agent_should_run(fields):
        try:
            agent_fields = _agent_fields_from_di_text(di_text, settings=cfg)
        except Exception:  # noqa: BLE001
            agent_fields = {}
        if agent_fields:
            agent_used = True
            # Agent wins on gaps and on suspicious phone-as-ID / tiny charge.
            for key, value in agent_fields.items():
                if key not in fields:
                    fields[key] = value
                    continue
                if key == "insured_id_number":
                    cur = re.sub(r"\D", "", fields[key])
                    if len(cur) in {7, 10} or not (8 <= len(cur) <= 12):
                        fields[key] = value
                elif key == "total_charge" and re.fullmatch(
                    r"\$?\d{1,2}\.\d{2}", fields[key]
                ):
                    fields[key] = value

    if not fields:
        return UnstructuredRegFallbackResult(
            attempted=True,
            configured=True,
            reason="UNSTRUCTURED_NO_SHAPED_FIELDS",
            di_text=di_text,
            agent_used=agent_used,
        )
    return UnstructuredRegFallbackResult(
        attempted=True,
        configured=True,
        reason="UNSTRUCTURED_REG_FALLBACK_OK",
        di_text=di_text,
        fields=fields,
        field_reasons={k: "UNSTRUCTURED_DI_SHAPED" for k in fields},
        agent_used=agent_used,
    )
