#!/usr/bin/env python3
"""DEPRECATED wrapper: delegates to measurement-integrity sync.

Prefer: python3 scripts/sync_ui_measurement_integrity.py
"""

from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("sync_ui_measurement_integrity.py")), run_name="__main__")
