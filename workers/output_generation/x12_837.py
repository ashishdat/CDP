"""X12 837 (professional/institutional claim EDI) output -- optional
adapter interface only. Not implemented: X12 837 is a full EDI standard
(segments, loops, envelope structure) orthogonal to the fixed-width NSF/
UB92 formats this platform was built against, and no sample 837 output
was supplied to validate against (see docs/DATASET_FINDINGS.md). Wiring a
real implementation means picking a concrete X12 library and is a later,
separate effort -- not a Phase 3 blocker.
"""

from __future__ import annotations

from typing import Protocol

from packages.domain.claim import Claim


class X12NotImplementedError(NotImplementedError):
    pass


class X12_837Adapter(Protocol):
    def render(self, claim: Claim) -> bytes: ...


class UnimplementedX12_837Adapter:
    def render(self, claim: Claim) -> bytes:
        raise X12NotImplementedError(
            "X12 837 output is not implemented -- no sample 837 output was supplied "
            "to validate against; see docs/DATASET_FINDINGS.md and "
            "docs/IMPLEMENTATION_PLAN.md"
        )
