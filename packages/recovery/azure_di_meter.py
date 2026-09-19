"""Append-only meter for billable Azure Document Intelligence calls.

Keeps local residuals (document-quad, LightGlue, TrOCR) free of cloud cost
while making DI usage visible for low-cost ops runs.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

_LOCK = threading.Lock()
_COUNTS: dict[str, int] = {
    "dob_crop": 0,
    "page_corners": 0,
    "other": 0,
}


def azure_di_error_detail(exc: BaseException) -> str:
    """Exception class plus a short message. No crop bytes, no field values."""
    text = " ".join(str(exc).split())[:120]
    name = type(exc).__name__
    if not text or text == name:
        return name
    return f"{name}:{text}"


def azure_di_meter_path() -> Path:
    raw = (os.environ.get("CDP_AZURE_DI_METER_PATH") or "").strip()
    if raw:
        return Path(raw)
    return Path("evaluation_results") / "azure_di_meter.jsonl"


def record_azure_di_call(
    *,
    kind: str,
    document_id: str | None = None,
    field_name: str | None = None,
    ok: bool = True,
    detail: str | None = None,
) -> None:
    """Record one billable DI analyze invocation (crop or page)."""
    key = kind if kind in _COUNTS else "other"
    path = azure_di_meter_path()
    row = {
        "ts": datetime.now(UTC).isoformat(),
        "kind": kind,
        "document_id": document_id,
        "field_name": field_name,
        "ok": ok,
        "detail": detail,
    }
    with _LOCK:
        _COUNTS[key] = int(_COUNTS.get(key, 0)) + 1
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def azure_di_call_counts() -> dict[str, int]:
    with _LOCK:
        return dict(_COUNTS)


def azure_di_page_corners_enabled() -> bool:
    """Full-page DI corners are billable — require explicit enable."""
    env = (os.environ.get("CDP_AZURE_DI_PAGE_CORNERS") or "").strip().casefold()
    if env in {"1", "true", "yes", "on"}:
        return True
    if env in {"0", "false", "no", "off"}:
        return False
    try:
        from packages.tool_escalation import load_secondary_policy

        policy = load_secondary_policy()
        return bool(policy.get("registration_azure_di_corners_enabled", False))
    except Exception:  # noqa: BLE001
        return False


def learned_matcher_enabled() -> bool:
    env = (os.environ.get("CDP_LEARNED_MATCHER") or "1").strip().casefold()
    return env not in {"0", "false", "no", "off"}
