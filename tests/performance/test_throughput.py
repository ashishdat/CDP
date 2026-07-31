"""Performance harness: pages/sec, p50/p95/p99 latency, and CPU
utilization for the pipeline stages that are actually real today (TIFF
decode + preprocessing, and page-routing's OpenCV signals) -- run against
every real sample TIFF in the supplied dataset, not synthetic images.

**What this does NOT measure, and why:**
- OCR/VLM invocation rates, GPU utilization: no OCR/VLM engine is wired to
  a live model in this environment (PaddleOCR needs the `[ml]` extras
  group; the VLM needs a running vLLM server) -- see docs/DATASET_FINDINGS.md
  and docs/ARCHITECTURE.md §12. Measuring zero would be misleading, so
  these are simply not reported rather than faked.
- Estimated cost per page: `packages.model_router.cost_table` gives a
  cost *per extraction method*, but "cost per page" depends on the
  escalation-path distribution across a real claim population, which
  doesn't exist without live extraction. `test_illustrative_cost_per_page`
  computes a clearly-labeled projection under a stated assumption instead
  of presenting a measured number.
- Straight-through processing rate: depends on the full extract ->
  validate -> (retry/VLM/review) pipeline being wired end-to-end
  (docs/IMPLEMENTATION_PLAN.md Phase 4/5 follow-up), not yet true here.

Run explicitly: `pytest tests/performance -m performance -s` (the `-s` so
the printed report isn't captured). Requires `dataset_raw/` (skipped
otherwise, like every other real-data test in this project).
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field

import psutil
import pytest

from packages.domain.enums import ExtractionMethod
from packages.model_router.cost_table import DEFAULT_COST_TABLE
from tests.conftest import FakeObjectStore, requires_dataset
from workers.document_preparation.codecs import decode_tiff_pages
from workers.document_preparation.pipeline import DocumentPreparationService
from workers.page_detection.grid_signature import compute_grid_signature

pytestmark = [pytest.mark.performance, requires_dataset]


@dataclass
class LatencySample:
    values_seconds: list[float] = field(default_factory=list)

    def add(self, seconds: float) -> None:
        self.values_seconds.append(seconds)

    def percentile(self, p: float) -> float:
        if not self.values_seconds:
            return 0.0
        ordered = sorted(self.values_seconds)
        index = min(int(len(ordered) * p), len(ordered) - 1)
        return ordered[index]

    def report(self, label: str) -> str:
        if not self.values_seconds:
            return f"{label}: no samples"
        total = sum(self.values_seconds)
        return (
            f"{label}: n={len(self.values_seconds)} "
            f"total={total:.3f}s pages/sec={len(self.values_seconds) / total:.2f} "
            f"p50={self.percentile(0.50) * 1000:.1f}ms "
            f"p95={self.percentile(0.95) * 1000:.1f}ms "
            f"p99={self.percentile(0.99) * 1000:.1f}ms "
            f"mean={statistics.mean(self.values_seconds) * 1000:.1f}ms"
        )


def _all_sample_files(dataset_raw_dir):
    return sorted(
        p for group in sorted(dataset_raw_dir.glob("Group *")) for p in sorted(group.glob("*.0*"))
    )


def test_decode_and_preprocess_throughput(dataset_raw_dir, capsys):
    files = _all_sample_files(dataset_raw_dir)
    assert len(files) == 30  # sanity check against docs/DATASET_FINDINGS.md

    decode_latency = LatencySample()
    prepare_latency = LatencySample()
    object_store = FakeObjectStore()
    service = DocumentPreparationService(object_store, bucket="idp-documents")

    process = psutil.Process()
    process.cpu_percent()  # first call primes the internal counter, discard it
    wall_start = time.perf_counter()

    for path in files:
        data = path.read_bytes()

        decode_start = time.perf_counter()
        pages = decode_tiff_pages(data)
        decode_elapsed = time.perf_counter() - decode_start
        for _ in pages:
            decode_latency.add(decode_elapsed / len(pages))

        prepare_start = time.perf_counter()
        # DocumentPreparationService.prepare() needs a Document for its
        # object-key naming only; a minimal one is enough here.
        document = _minimal_document(data)
        prepared_pages = service.prepare(document, data)
        prepare_elapsed = time.perf_counter() - prepare_start
        for _ in prepared_pages:
            prepare_latency.add(prepare_elapsed / len(prepared_pages))

    wall_elapsed = time.perf_counter() - wall_start
    cpu_percent = process.cpu_percent()  # average over the interval just measured

    with capsys.disabled():
        print("\n--- Performance harness: decode + preprocess (real dataset, 30 files) ---")
        print(decode_latency.report("TIFF decode"))
        print(prepare_latency.report("Full prepare (decode+deskew+denoise+thumbnail)"))
        print(f"Wall time: {wall_elapsed:.2f}s  Process CPU utilization: {cpu_percent:.1f}%")
        print(
            "(CPU utilization can exceed 100% on multi-core hosts -- psutil reports "
            "cores-as-percent, e.g. 250% == 2.5 cores busy)"
        )

    assert prepare_latency.values_seconds  # the harness itself ran and produced data


def test_page_routing_signal_throughput(dataset_raw_dir, capsys):
    """Grid-signature computation (the cheapest real page-routing signal,
    Phase 2) -- separate from decode/preprocess since it's on the fast
    path for every page in Bundle B/D routing."""
    files = _all_sample_files(dataset_raw_dir)
    latency = LatencySample()

    for path in files:
        pages = decode_tiff_pages(path.read_bytes())
        for page in pages:
            start = time.perf_counter()
            compute_grid_signature(page.image)
            latency.add(time.perf_counter() - start)

    with capsys.disabled():
        print("\n--- Performance harness: grid-signature computation ---")
        print(latency.report("Grid signature"))

    assert latency.values_seconds


def test_illustrative_cost_per_page(capsys):
    """NOT a measurement -- a clearly-labeled projection of
    estimated_cost_usd_total per page under a stated escalation-mix
    assumption, using the real cost table from packages.model_router.
    Replace the assumed distribution with real telemetry once the full
    pipeline is wired end-to-end (see this file's module docstring)."""
    assumed_distribution = {
        ExtractionMethod.REGIONAL_PADDLEOCR: 0.85,
        ExtractionMethod.ALTERNATE_PREPROCESS_OCR: 0.10,
        ExtractionMethod.LAYOUTLMV3: 0.03,
        ExtractionMethod.VLM_FALLBACK: 0.015,
        ExtractionMethod.HUMAN_REVIEW: 0.005,
    }
    assert sum(assumed_distribution.values()) == pytest.approx(1.0)

    projected_cost_per_page = sum(
        DEFAULT_COST_TABLE[method] * fraction for method, fraction in assumed_distribution.items()
    )

    with capsys.disabled():
        print("\n--- Illustrative (NOT measured) cost per page ---")
        for method, fraction in assumed_distribution.items():
            print(f"  {method.value:24s} {fraction:.1%} of fields x ${DEFAULT_COST_TABLE[method]:.4f}")
        print(f"  Projected cost/page (field-level, assumed mix): ${projected_cost_per_page:.5f}")
        print("  (Assumed distribution, not measured -- see this test's docstring.)")


def _minimal_document(data: bytes):
    from uuid import uuid4

    from packages.domain.common import ObjectRef
    from packages.domain.document import Document
    from packages.domain.enums import SourceFormat
    from packages.storage.hashing import sha256_bytes

    digest = sha256_bytes(data)
    return Document(
        document_id=uuid4(),
        tenant_id="perf-harness",
        source_filename="perf.tiff",
        detected_format=SourceFormat.TIFF,
        sha256=digest,
        original_object=ObjectRef(bucket="idp-documents", key=f"documents/perf/{digest}.tiff"),
        pipeline_version="0.1.0",
        schema_version="1.0",
    )
