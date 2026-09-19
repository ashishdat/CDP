"""Subprocess bridge to isolated PP-OCRv5 Server (paddleocr 3.x venv).

Stable workers stay on paddleocr 2.x / PP-OCRv4. When
``CDP_PPOCRV5_SERVER`` is enabled, charge crops can call this bridge which
runs ``.venv-ppocrv5`` without importing paddle 3 into the main process.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VENV_PY = ROOT / ".venv-ppocrv5" / "bin" / "python"

_WORKER = r"""
import json, os, sys
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_enable_pir_api", "0")
os.environ.setdefault("FLAGS_enable_pir_in_executor", "0")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
import paddle
paddle.set_flags({"FLAGS_use_mkldnn": False})
from paddleocr import PaddleOCR
from PIL import Image
import numpy as np

path = sys.argv[1]
ocr = PaddleOCR(
    text_detection_model_name="PP-OCRv5_server_det",
    text_recognition_model_name="PP-OCRv5_server_rec",
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    device="cpu",
    enable_mkldnn=False,
)
img = Image.open(path).convert("RGB")
out = list(ocr.predict(np.asarray(img)))
texts, scores = [], []
for result in out:
    payload = result.json if hasattr(result, "json") else result
    if callable(payload):
        payload = payload()
    if isinstance(payload, dict) and "res" in payload:
        payload = payload["res"]
    texts = [str(t).strip() for t in (payload.get("rec_texts") or []) if str(t).strip()]
    scores = [float(s) for s in (payload.get("rec_scores") or [])]
print(json.dumps({"texts": texts, "scores": scores}))
"""


def ppocr_v5_server_enabled() -> bool:
    raw = (os.environ.get("CDP_PPOCRV5_SERVER") or "0").strip().casefold()
    return raw not in {"0", "false", "no", "off", ""}


def venv_python() -> Path:
    override = (os.environ.get("CDP_PPOCRV5_PYTHON") or "").strip()
    return Path(override) if override else DEFAULT_VENV_PY


def recognize_ppocr_v5_server(
    crop: Image.Image,
    *,
    timeout_sec: float = 60.0,
) -> tuple[str | None, float, str]:
    """Return (best_text, confidence, reason) from PP-OCRv5 Server via venv.

    reason is OBSERVED / EMPTY / error code. Never raises into the cascade.
    """
    py = venv_python()
    if not py.is_file():
        return None, 0.0, "PPOCRV5_VENV_MISSING"
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        path = tmp.name
        crop.convert("RGB").save(path)
    try:
        proc = subprocess.run(
            [str(py), "-c", _WORKER, path],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, 0.0, f"PPOCRV5_SUBPROCESS:{type(exc).__name__}"
    finally:
        Path(path).unlink(missing_ok=True)
    if proc.returncode != 0:
        return None, 0.0, "PPOCRV5_FAILED"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    if not lines:
        return None, 0.0, "PPOCRV5_NO_JSON"
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None, 0.0, "PPOCRV5_BAD_JSON"
    texts = [str(t).strip() for t in (payload.get("texts") or []) if str(t).strip()]
    scores = [float(s) for s in (payload.get("scores") or [])]
    if not texts:
        return None, 0.0, "PPOCRV5_EMPTY"
    # Prefer the longest digit-bearing token for charge crops.
    best_i = 0
    best_key = (-1, -1.0)
    for i, text in enumerate(texts):
        digits = sum(ch.isdigit() for ch in text)
        score = scores[i] if i < len(scores) else 0.0
        key = (digits, score)
        if key > best_key:
            best_key = key
            best_i = i
    return texts[best_i], (scores[best_i] if best_i < len(scores) else 0.0), "OBSERVED"
