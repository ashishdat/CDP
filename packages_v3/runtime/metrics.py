"""Content-free comparison and best-effort runtime reporting."""

import logging

from .models import STAGES, PipelineComparison, RuntimeReport

logger = logging.getLogger(__name__)


def compare(left, right) -> str:
    try:
        return "equal" if left == right else "different"
    except Exception:  # noqa: BLE001 -- diagnostics cannot fail a request
        return "unavailable"


def comparison(legacy_snapshots, v3_snapshots, legacy_value, v3_value, *, comparable):
    stages = tuple(
        (
            name,
            compare(legacy_snapshots[name], v3_snapshots[name])
            if name in legacy_snapshots and name in v3_snapshots
            else "unavailable",
        )
        for name in STAGES
    )
    return PipelineComparison(
        stages, compare(legacy_value, v3_value) if comparable else "unavailable"
    )


def log_report(report: RuntimeReport) -> None:
    # No fields, OCR text, document pixels, or exception messages are logged.
    logger.info("v3_runtime", extra={"runtime_report": report})


def emit(sink, report: RuntimeReport) -> None:
    try:
        sink(report)
    except Exception:  # noqa: BLE001, S110 -- observability must not change runtime outcomes
        pass
