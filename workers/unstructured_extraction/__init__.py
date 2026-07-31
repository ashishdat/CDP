"""Bundle D (unstructured claim documents) and UB failed-table extraction
adapter interfaces. Neither LayoutLMv3 nor Table Transformer is trained/
wired yet -- see the module docstrings for what's real vs. interface-only.

Bundle D's own PaddleOCR + configured-schema extraction worker is not
implemented yet either — see docs/IMPLEMENTATION_PLAN.md.
"""

from workers.unstructured_extraction.handwriting_service import HandwritingFallbackService
from workers.unstructured_extraction.layoutlmv3_adapter import (
    LayoutFieldResult,
    LayoutLMv3Adapter,
    LayoutModelAdapter,
)
from workers.unstructured_extraction.table_transformer_adapter import (
    TableCell,
    TableModelAdapter,
    TableTransformerAdapter,
)
from workers.unstructured_extraction.trocr_adapter import (
    HandwritingRecognizer,
    TrOCRAdapter,
    TrOCRResult,
)

__all__ = [
    "HandwritingFallbackService",
    "HandwritingRecognizer",
    "LayoutFieldResult",
    "LayoutLMv3Adapter",
    "LayoutModelAdapter",
    "TableCell",
    "TableModelAdapter",
    "TableTransformerAdapter",
    "TrOCRAdapter",
    "TrOCRResult",
]
