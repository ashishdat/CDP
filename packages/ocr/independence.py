"""OCR family classification (one dependency signal, never independence proof)."""


def independence_group(engine: str) -> str:
    normalized = engine.lower()
    if "rapidocr" in normalized:
        return "RAPIDOCR_FAMILY"
    if "openocr" in normalized or "svtr" in normalized:
        return "PADDLE_FAMILY"
    if "monkeyocr" in normalized:
        return "VL_TABLE_FAMILY"
    if "paddleocr_vl" in normalized or "paddleocr-vl" in normalized:
        return "VL_TABLE_FAMILY"
    if "paddle" in normalized or "pp-ocr" in normalized or "ppocr" in normalized:
        return "PADDLE_FAMILY"
    if "tesseract" in normalized:
        return "TESSERACT_FAMILY"
    if "gemini" in normalized:
        return "GEMINI_FAMILY"
    if "textract" in normalized:
        return "TEXTRACT_FAMILY"
    if "trocr" in normalized:
        return "TROCR_FAMILY"
    if "florence" in normalized:
        return "FLORENCE_FAMILY"
    if "got-ocr" in normalized or "got_ocr" in normalized:
        return "GOT_OCR_FAMILY"
    # gpt-4o / Claude crop residuals before generic "azure" (DI Read) match.
    if (
        "gpt4o" in normalized
        or "gpt-4o" in normalized
        or "openai" in normalized
        or "claude" in normalized
        or "anthropic" in normalized
    ):
        return "CLOUD_AI_FAMILY"
    if "azure" in normalized:
        return "AZURE_READ_FAMILY"
    return normalized.upper()


def engines_are_independent(*_engines: str) -> bool:
    """Prevent legacy callers from equating different names with independence."""
    return False
