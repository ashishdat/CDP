"""Time a frozen production-contract replay and regenerate the governed report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter


def _run(*arguments: str) -> None:
    subprocess.run([sys.executable, *arguments], check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("evaluation_data/contracts/evaluation_contract_v3.json"),
    )
    parser.add_argument(
        "--predictions", type=Path, default=Path("evaluation_results/predictions_v3")
    )
    parser.add_argument(
        "--timing-output",
        type=Path,
        default=Path("evaluation_results/runtime/latest_process_timing.json"),
    )
    args = parser.parse_args()

    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    pages = {
        (
            field["field_identity"]["document_id"],
            int(field["field_identity"].get("page_number") or 1),
        )
        for field in contract["fields"]
    }
    started_at = datetime.now(UTC)
    started = perf_counter()
    _run(
        "evaluation/run_production_contract.py",
        "--contract",
        str(args.contract),
        "--output",
        str(args.predictions),
    )
    processing_seconds = perf_counter() - started
    page_count = len(pages)
    timing = {
        "schema_version": "production-replay-timing-v1",
        "scope": "FROZEN_PRODUCTION_CONTRACT_REPLAY",
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "processing_time_seconds": processing_seconds,
        "total_pages_processed": page_count,
        "total_fields_processed": len(contract["fields"]),
        "average_latency_seconds": processing_seconds / page_count if page_count else None,
        "pages_per_second": page_count / processing_seconds if processing_seconds else None,
        "fresh_ocr_calls": 0,
        "fresh_llm_calls": 0,
        "uses_persisted_candidates": True,
        "ground_truth_available_to_inference": False,
        "note": (
            "Measures frozen production candidate assembly, deterministic parsing and "
            "reconciliation. It excludes fresh OCR/LLM inference, model cold start and network latency."
        ),
    }
    args.timing_output.parent.mkdir(parents=True, exist_ok=True)
    args.timing_output.write_text(json.dumps(timing, indent=2), encoding="utf-8")
    print(json.dumps(timing, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
