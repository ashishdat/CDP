"""Registration evidence for fixed healthcare claim forms."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw

SPECS = {
    "CMS1500": Path("config/table_templates/cms1500_service_lines.yaml"),
    "UB04": Path("config/table_templates/ub04_service_lines.yaml"),
}


@dataclass(frozen=True)
class RegistrationResult:
    registered_page: Image.Image
    matrix: list[list[float]]
    residual_error: float
    status: str
    anchor_matches: list[dict]


def load_spec(family: str) -> dict:
    return yaml.safe_load(SPECS[family].read_text(encoding="utf-8"))


def _line_near(gray: np.ndarray, expected: int, axis: int, radius: int = 12) -> int:
    binary = gray < 100
    projection = binary.mean(axis=axis)
    start, end = max(0, expected - radius), min(len(projection), expected + radius + 1)
    return start + int(np.argmax(projection[start:end]))


def register_page(page: Image.Image, family: str) -> RegistrationResult:
    spec = load_spec(family)
    width, height = spec["reference_dimensions"]
    registered = page.convert("RGB").resize((width, height))
    gray = np.asarray(registered.convert("L"))
    expected = spec["registration"]["anchors"]
    left = _line_near(gray, expected[0][0], axis=0)
    right = _line_near(gray, expected[1][0], axis=0)
    top = _line_near(gray, expected[0][1], axis=1)
    bottom = _line_near(gray, expected[2][1], axis=1)
    observed = [(left, top), (right, top), (left, bottom), (right, bottom)]
    errors = [
        float(np.hypot(actual[0] - target[0], actual[1] - target[1]))
        for actual, target in zip(observed, expected, strict=True)
    ]
    residual = float(np.mean(errors))
    threshold = float(spec["registration"]["maximum_residual_error_px"])
    matrix = [
        [width / page.width, 0.0, 0.0],
        [0.0, height / page.height, 0.0],
        [0.0, 0.0, 1.0],
    ]
    return RegistrationResult(
        registered_page=registered,
        matrix=matrix,
        residual_error=residual,
        status="REGISTERED" if residual <= threshold else "REGISTRATION_FAILED",
        anchor_matches=[
            {"expected": target, "observed": actual, "error": error}
            for target, actual, error in zip(expected, observed, errors, strict=True)
        ],
    )


def persist_registration(
    result: RegistrationResult, family: str, output: Path
) -> dict[str, str]:
    output.mkdir(parents=True, exist_ok=True)
    spec = load_spec(family)
    width, height = spec["reference_dimensions"]
    canonical = Image.new("RGB", (width, height), "white")
    canonical_draw = ImageDraw.Draw(canonical)
    rows = spec["rows"]
    for index in range(rows["count"] + 1):
        y = round(
            rows["first_y"]
            + index * (rows["last_y"] - rows["first_y"]) / rows["count"]
        )
        canonical_draw.line((spec["fields"][0]["x0"], y, spec["fields"][-1]["x1"], y), fill="black")
    for field in spec["fields"]:
        canonical_draw.line(
            (field["x0"], rows["first_y"], field["x0"], rows["last_y"]),
            fill="black",
        )
    canonical_path = output / "canonical_template.png"
    registered_path = output / "registered_page.png"
    overlay_path = output / "registration_overlay.png"
    canonical.save(canonical_path)
    result.registered_page.save(registered_path)
    overlay = result.registered_page.copy()
    draw = ImageDraw.Draw(overlay)
    for match in result.anchor_matches:
        x, y = match["observed"]
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), outline="red", width=2)
    overlay.save(overlay_path)
    evidence_path = output / "registration.json"
    evidence_path.write_text(
        json.dumps(
            {
                "matrix": result.matrix,
                "residual_error": result.residual_error,
                "status": result.status,
                "anchor_matches": result.anchor_matches,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "canonical_template": str(canonical_path),
        "registered_page": str(registered_path),
        "registration_overlay": str(overlay_path),
        "registration_evidence": str(evidence_path),
    }
