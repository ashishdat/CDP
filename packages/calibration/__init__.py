"""Calibration package — leakage-safe development-only training."""

from .dataset import CalibrationDataset, CalibrationExample, select_threshold_for_precision

__all__ = [
    "CalibrationDataset",
    "CalibrationExample",
    "select_threshold_for_precision",
]
