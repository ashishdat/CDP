"""Match truth and predictions without silently dropping missing/extra fields."""

from __future__ import annotations

from dataclasses import dataclass

from evaluation.schemas import (
    GroundTruthDataset,
    GroundTruthDocument,
    GroundTruthField,
    PredictedField,
    PredictionDataset,
)


@dataclass(frozen=True)
class FieldPair:
    document: GroundTruthDocument
    truth: GroundTruthField
    prediction: PredictedField | None


def match_fields(truth: GroundTruthDataset, predictions: PredictionDataset) -> list[FieldPair]:
    predicted_documents = {document.document_id: document for document in predictions.documents}
    pairs: list[FieldPair] = []
    for document in truth.documents:
        predicted = predicted_documents.get(document.document_id)
        by_name = {field.field_name: field for field in predicted.fields} if predicted else {}
        pairs.extend(FieldPair(document, field, by_name.get(field.field_name)) for field in document.fields)
    return pairs
