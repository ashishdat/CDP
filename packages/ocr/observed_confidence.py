"""Normalize provider-reported raw confidence without manufacturing calibration."""
import math


def observed_confidence(value):
    if isinstance(value,bool):return None
    try:value=float(value)
    except (TypeError,ValueError):return None
    return value if math.isfinite(value) and 0 <= value <= 1 else None
