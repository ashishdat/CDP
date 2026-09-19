"""OCR portfolio helpers: controlled variants and adapter contracts."""

from .monetary_recognizer import (
    MonetaryRead,
    MonetaryRecognizeResult,
    monetary_variants_extended,
    prefer_charge_ink_amount,
    recognize_monetary_crop,
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
    "prefer_charge_ink_amount",
    "recognize_monetary_crop",
    "shape_monetary",
    "split_charge_at_vertical_ruling",
]
