"""The three not-yet-trained model adapters (MobileNetV3 page classifier,
LayoutLMv3, Table Transformer) all follow the same contract: fail loudly
and specifically with `ModelNotAvailableError` when reached, never
silently no-op -- callers (the model router / page router) are expected
to treat that exception as "escalate further," not "retry this route."
"""

import pytest
from PIL import Image

from workers.page_detection.mobilenet_classifier import (
    MobileNetV3PageClassifier,
)
from workers.page_detection.mobilenet_classifier import (
    ModelNotAvailableError as PageClassifierNotAvailable,
)
from workers.unstructured_extraction.layoutlmv3_adapter import LayoutLMv3Adapter
from workers.unstructured_extraction.layoutlmv3_adapter import (
    ModelNotAvailableError as LayoutNotAvailable,
)
from workers.unstructured_extraction.table_transformer_adapter import (
    ModelNotAvailableError as TableNotAvailable,
)
from workers.unstructured_extraction.table_transformer_adapter import TableTransformerAdapter


def _image() -> Image.Image:
    return Image.new("L", (100, 100), color=255)


def test_mobilenet_classifier_without_checkpoint_raises():
    classifier = MobileNetV3PageClassifier()
    with pytest.raises(PageClassifierNotAvailable):
        classifier.classify(_image())


def test_layoutlmv3_without_checkpoint_raises():
    adapter = LayoutLMv3Adapter()
    with pytest.raises(LayoutNotAvailable):
        adapter.extract(_image(), field_schema=["patient_name"])


def test_table_transformer_without_checkpoint_raises():
    adapter = TableTransformerAdapter()
    with pytest.raises(TableNotAvailable):
        adapter.extract_table(_image())
