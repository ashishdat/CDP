"""Phase 8.10 extraction recovery primitives."""

from .contracts import (
    CandidateObservation,
    CandidateRankingResult,
    ExtractionFailureType,
    SpanSelectionResult,
    WrongCropAssessment,
)
from .crop_recovery import bounded_expand_bbox
from .failure_analysis import classify_extraction_failure
from .ranking import CandidateScoringPolicy, rank_candidates
from .roi_insets import ROI_INSETS, inset_bbox
from .span_selection import select_field_span, span_datatype_for_field
from .field_cascade import (
    FieldCascade,
    CascadeResult,
    charge_column_windows,
    crop_variants,
    load_route_engines,
    semantic_accept,
)
from .wrong_crop import WrongCropDetector

__all__ = [
    "CandidateObservation",
    "CandidateRankingResult",
    "CandidateScoringPolicy",
    "ExtractionFailureType",
    "SpanSelectionResult",
    "WrongCropAssessment",
    "WrongCropDetector",
    "bounded_expand_bbox",
    "classify_extraction_failure",
    "rank_candidates",
    "ROI_INSETS",
    "inset_bbox",
    "select_field_span",
    "span_datatype_for_field",
    "FieldCascade",
    "CascadeResult",
    "charge_column_windows",
    "crop_variants",
    "load_route_engines",
    "semantic_accept",
]
