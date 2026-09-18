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
from .field_cascade import (
    CascadeResult,
    FieldCascade,
    charge_column_windows,
    crop_variants,
    load_route_engines,
    pick_engine_candidates,
    semantic_accept,
)
from .gap_taxonomy import GapClassification, classify_field_gap
from .ranking import CandidateScoringPolicy, rank_candidates
from .roi_insets import ROI_INSETS, inset_bbox
from .span_selection import select_field_span, span_datatype_for_field
from .strategy import crop_ladder_for, load_cascade_strategy, post_miss_for
from .wrong_crop import WrongCropDetector

__all__ = [
    "ROI_INSETS",
    "CandidateObservation",
    "CandidateRankingResult",
    "CandidateScoringPolicy",
    "CascadeResult",
    "ExtractionFailureType",
    "FieldCascade",
    "GapClassification",
    "SpanSelectionResult",
    "WrongCropAssessment",
    "WrongCropDetector",
    "bounded_expand_bbox",
    "charge_column_windows",
    "classify_extraction_failure",
    "classify_field_gap",
    "crop_ladder_for",
    "crop_variants",
    "inset_bbox",
    "load_cascade_strategy",
    "load_route_engines",
    "pick_engine_candidates",
    "post_miss_for",
    "rank_candidates",
    "select_field_span",
    "semantic_accept",
    "span_datatype_for_field",
]
