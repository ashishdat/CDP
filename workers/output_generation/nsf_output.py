"""NSF fixed-width output, assembled from whatever record types are
currently transcribed in `config/output_specs/nsf/` (today: AA0, BA0,
BA1, CA0 -- see docs/DATASET_FINDINGS.md for which record types the full
format defines and docs/IMPLEMENTATION_PLAN.md for the rest).

**This does not produce a complete, submittable NSF file.** A real
submission also needs EA0 (claim data), FA0 (one per service line), HA0
(narrative, conditional), and the XA0/YA0/ZA0 trailer records -- none of
which are transcribed yet. What this module proves is the *mechanism*:
resolving claim data through the config-driven writer produces
byte-correct records for every record type that *is* configured, which is
exactly what `tests/golden` checks against the real reference output.

NSF also mixes claim-scoped data (patient, in CA0) with batch/submission-
scoped data (submitter identity in AA0, batch number in BA0/BA1) that
doesn't belong on a single `Claim` -- callers supply that as
`batch_context`, keyed by record type.
"""

from __future__ import annotations

from packages.domain.claim import Claim
from packages.fixed_width.resolver import resolve_source_field
from packages.fixed_width.spec_models import FixedWidthRecordSpec
from packages.fixed_width.writer import FixedWidthWriter

# Only record types with a defined, sensible claim-derived mapping. AA0
# (file header) and part of BA0/BA1 (batch/provider) are almost entirely
# `batch_context` today because that data belongs to a submission batch,
# not to a single Claim -- see module docstring.
CLAIM_DERIVED_RECORD_TYPES = ("AA0", "BA0", "BA1", "CA0")


class NSFOutputWriter:
    def __init__(self, specs: dict[str, FixedWidthRecordSpec]) -> None:
        self._specs = specs

    def render_record(
        self, record_type: str, claim: Claim, batch_context: dict[str, str] | None = None
    ) -> str:
        spec = self._specs[record_type]
        writer = FixedWidthWriter(spec)

        field_values: dict[str, str] = dict(batch_context or {})
        for field_spec in spec.fields:
            if field_spec.field_name in field_values:
                continue  # batch_context takes precedence over a source_field mapping
            if field_spec.source_field:
                field_values[field_spec.field_name] = resolve_source_field(
                    claim, field_spec.source_field
                )
        return writer.render_record(field_values)

    def render_available_records(
        self, claim: Claim, batch_context: dict[str, dict[str, str]] | None = None
    ) -> list[str]:
        """Renders every configured record type from `CLAIM_DERIVED_RECORD_TYPES`
        that this writer has a spec for, in that order. `batch_context` is
        `{record_type: {field_name: value}}`."""
        batch_context = batch_context or {}
        return [
            self.render_record(record_type, claim, batch_context.get(record_type))
            for record_type in CLAIM_DERIVED_RECORD_TYPES
            if record_type in self._specs
        ]
