#!/usr/bin/env python3
"""Smoke-test Azure Document Intelligence prebuilt-read using Settings/.env.

Exits 0 on successful analyze (even if content is empty). Never prints the API key.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.domain.common import BoundingBox
from packages.domain.enums import ClaimFormType
from packages.ocr.contracts import OCRRequest
from packages.settings import Settings
from workers.cascade.azure_di_factory import (
    AzureDocumentIntelligenceConfigurationError,
    azure_document_intelligence_configured,
    build_azure_read_engine,
)


def main() -> int:
    settings = Settings()
    print("di_enabled", settings.azure_document_intelligence_enabled)
    print("di_endpoint_set", bool(settings.azure_document_intelligence_endpoint or settings.cloud_handwriting_endpoint))
    print("di_key_set", bool(settings.azure_document_intelligence_api_key or settings.cloud_handwriting_credential))
    print("di_configured", azure_document_intelligence_configured(settings))
    if not azure_document_intelligence_configured(settings):
        print("status", "NOT_CONFIGURED")
        print(
            "need",
            "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT + API_KEY + ENABLED + AUTHORIZED + "
            "REGION_APPROVED + PHI_CONTRACT_APPROVED",
        )
        return 2
    try:
        engine = build_azure_read_engine(settings)
    except AzureDocumentIntelligenceConfigurationError as exc:
        print("status", "CONFIG_ERROR", str(exc))
        return 2
    # Azure DI rejects tiny / empty crops (InvalidContentDimensions).
    from PIL import ImageDraw

    img = Image.new("RGB", (400, 120), "white")
    ImageDraw.Draw(img).text((24, 44), "03/15/1968", fill=(0, 0, 0))
    request = OCRRequest(
        document_id="di-smoke",
        page_number=1,
        field_name="patient_dob",
        field_type="date",
        form_type=ClaimFormType.CMS1500,
        image=img,
        bounding_box=BoundingBox(x0=0, y0=0, x1=400, y1=120, image_width=400, image_height=120),
    )
    candidates = engine.recognize(request)
    cand = candidates[0] if candidates else None
    print("status", "OK")
    print("engine", engine.engine_name)
    print("model", engine.model_name)
    print("value", None if cand is None else cand.value)
    print("confidence", None if cand is None else cand.raw_confidence)
    print("review_only", None if cand is None else ("SHADOW_REVIEW_ONLY" in (cand.validation_results or ())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
