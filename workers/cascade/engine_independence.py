"""Independence groups used by the shadow-v2.1 reconciliation experiment."""


def independence_group(engine: str) -> str:
    normalized = engine.lower()
    if "paddle" in normalized or "pp-ocr" in normalized:
        return "PADDLE_FAMILY"
    if "tesseract" in normalized:
        return "TESSERACT_FAMILY"
    if "trocr" in normalized:
        return "TROCR_FAMILY"
    if "azure" in normalized:
        return "AZURE_READ_FAMILY"
    return normalized
