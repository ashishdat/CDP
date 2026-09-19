"""Rank → validate → assemble → complete in one process (STP cascade latency).

Avoids four Python cold-starts after OCR (~1–1.5s on this VM).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.assemble_extraction_result import assemble
from scripts.complete_from_extraction import run as complete_run
from scripts.rank_from_ocr import rank_saved
from scripts.validate_from_ranked import run as validate_run


def run(
    ocr_candidates: str | Path,
    claim_out: str | Path,
    *,
    template_id: str = "cms1500",
    template_version: str | None = None,
    document_family: str = "CMS1500",
) -> dict:
    claim_out = Path(claim_out)
    ocr_candidates = Path(ocr_candidates)
    rank_dir = claim_out / "rank"
    validate_dir = claim_out / "validate"
    extract_dir = claim_out / "extract"
    final_dir = claim_out / "final"

    if not template_version:
        try:
            from scripts.run_hackathon_1000_cascade import _cms1500_template_version

            template_version = _cms1500_template_version()
        except Exception:  # noqa: BLE001
            import os

            release = (os.environ.get("CDP_PIPELINE_RELEASE") or "").strip().casefold()
            template_version = "03" if release in {"extraction-v3", "v3"} else "02-12"

    rank_saved(ocr_candidates, rank_dir)
    validate_run(
        rank_dir / "RankedCandidates.json",
        validate_dir,
        template_id,
        template_version,
    )
    assemble(
        ocr_candidates,
        rank_dir / "RankedCandidates.json",
        validate_dir / "ValidationResults.json",
        extract_dir,
    )
    final = complete_run(
        extract_dir / "ExtractionResult.json",
        final_dir,
        document_family,
    )
    return {
        "status": final.get("status"),
        "true_stp": bool(
            final.get("status") == "COMPLETED" and not final.get("review_required")
        ),
        "review_required": bool(final.get("review_required")),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ocr_candidates")
    parser.add_argument("claim_out")
    parser.add_argument("--template-id", default="cms1500")
    parser.add_argument("--template-version", default=None)
    parser.add_argument("--document-family", default="CMS1500")
    args = parser.parse_args()
    result = run(
        args.ocr_candidates,
        args.claim_out,
        template_id=args.template_id,
        template_version=args.template_version,
        document_family=args.document_family,
    )
    print(json.dumps(result))
