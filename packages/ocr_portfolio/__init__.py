"""OCR portfolio helpers: controlled variants and adapter contracts."""

from .monetary_recognizer import (
    MonetaryRead,
    MonetaryRecognizeResult,
    monetary_variants_extended,
    apply_charge_line_resolution,
    is_ruling_tick_charge,
    prefer_charge_ink_amount,
    recognize_monetary_crop,
    resolve_service_charge,
    recover_dollars_from_split_raw,
    shape_dollars_ruling_amount,
    shape_monetary,
    split_charge_at_vertical_ruling,
)
from .monetary_variants import CropVariant, iter_variant_ids, monetary_crop_variants

__all__ = [
    "CropVariant",
    "MonetaryRead",
    "MonetaryRecognizeResult",
    "iter_variant_ids",
    "monetary_crop_variants",
    "monetary_variants_extended",
    "apply_charge_line_resolution",
    "is_ruling_tick_charge",
    "prefer_charge_ink_amount",
    "resolve_service_charge",
    "recognize_monetary_crop",
    "recover_dollars_from_split_raw",
    "shape_dollars_ruling_amount",
    "shape_monetary",
    "split_charge_at_vertical_ruling",
]
