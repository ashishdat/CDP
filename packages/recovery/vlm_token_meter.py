"""Append-only meter for billable VLM (Claude / GPT-4o) token usage.

Mirrors ``azure_di_meter`` so Independent evals can report tokens consumed
alongside DI crop counts. Opt-in via ``CDP_VLM_TOKEN_METER_PATH``.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

_LOCK = threading.Lock()
_TOTALS: dict[str, int] = {
    "calls": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0,
}


def vlm_token_meter_path() -> Path | None:
    raw = (os.environ.get("CDP_VLM_TOKEN_METER_PATH") or "").strip()
    if not raw:
        return None
    return Path(raw)


def record_vlm_call(
    *,
    provider: str,
    engine: str | None = None,
    field_names: list[str] | None = None,
    document_id: str | None = None,
    kind: str = "crop",
    usage: Mapping[str, Any] | None = None,
    ok: bool = True,
    detail: str | None = None,
) -> None:
    """Record one VLM extract_fields invocation and its token usage."""
    path = vlm_token_meter_path()
    if path is None:
        return
    usage = usage or {}
    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    total_tokens = int(
        usage.get("total_tokens") or (input_tokens + output_tokens)
    )
    row = {
        "ts": datetime.now(UTC).isoformat(),
        "kind": kind,
        "provider": provider,
        "engine": engine,
        "document_id": document_id,
        "field_names": list(field_names or []),
        "ok": ok,
        "detail": detail,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }
    with _LOCK:
        _TOTALS["calls"] = int(_TOTALS.get("calls", 0)) + 1
        _TOTALS["input_tokens"] = int(_TOTALS.get("input_tokens", 0)) + input_tokens
        _TOTALS["output_tokens"] = int(_TOTALS.get("output_tokens", 0)) + output_tokens
        _TOTALS["total_tokens"] = int(_TOTALS.get("total_tokens", 0)) + total_tokens
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def vlm_token_totals() -> dict[str, int]:
    with _LOCK:
        return dict(_TOTALS)
