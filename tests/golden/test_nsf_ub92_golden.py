"""Golden tests: byte-for-byte round-trip of the transcribed NSF/UB92
record specs against the real supplied reference output files.

For every line in the reference `.txt` files whose record type we have a
transcribed spec for: parse it into named fields, re-render it with
`FixedWidthWriter`, and assert the result is byte-identical to the
original line. This is what "compare field positions and record lengths"
(per the platform spec's testing requirements) means in practice -- if a
single `start_position`/`length` were transcribed incorrectly, this test
fails on real data, not on a hand-crafted fixture that could accidentally
encode the same mistake twice.

Only 5 of the ~26 record types observed across the sample dataset are
transcribed so far (NSF AA0/BA0/BA1/CA0, UB92 01) -- see
docs/DATASET_FINDINGS.md and docs/IMPLEMENTATION_PLAN.md for the rest.
"""

import pytest

from packages.fixed_width import (
    FixedWidthWriter,
    load_nsf_specs,
    load_ub92_specs,
    parse_record,
)
from tests.conftest import requires_dataset

pytestmark = [pytest.mark.golden, requires_dataset]


def _read_lines(path) -> list[str]:
    with open(path, "rb") as f:
        data = f.read()
    return data.decode("ascii").split("\r\n")


def _assert_roundtrip(spec, line: str, context: str) -> None:
    parsed = parse_record(spec, line)
    rendered = FixedWidthWriter(spec).render_record(parsed)
    assert rendered == line, f"{context}: round-trip mismatch for record type {spec.record_type}"


@pytest.fixture(scope="module")
def nsf_specs():
    return load_nsf_specs()


@pytest.fixture(scope="module")
def ub92_specs():
    return load_ub92_specs()


@pytest.mark.parametrize(
    "relative_path",
    [
        "Group A/DATAMATICS_UBH_HCFA_07212026 - Group A.txt",
        "Group B/DATAMATICS_UBH_HCFA_07202026 - Group B.txt",
        "Group D/DATAMATICS_UBH_HCFA_07212026 - Group D.txt",
    ],
)
def test_nsf_transcribed_record_types_roundtrip_every_matching_line(
    dataset_raw_dir, nsf_specs, relative_path
):
    lines = _read_lines(dataset_raw_dir / relative_path)
    checked_record_types: set[str] = set()

    for line_number, line in enumerate(lines, start=1):
        if not line:
            continue
        record_type = line[:3]
        spec = nsf_specs.get(record_type)
        if spec is None:
            continue  # record type not transcribed yet -- not a failure
        _assert_roundtrip(spec, line, context=f"{relative_path} line {line_number}")
        checked_record_types.add(record_type)

    # sanity: every transcribed NSF record type actually appears at least
    # once in this file (AA0/BA0/BA1/CA0 are all present in every group)
    assert checked_record_types == set(nsf_specs.keys())


def test_ub92_transcribed_record_type_roundtrips_group_c(dataset_raw_dir, ub92_specs):
    lines = _read_lines(dataset_raw_dir / "Group C/DATAMATICS_UBH_UB_07202026 - Group C.txt")
    spec = ub92_specs["01"]
    # record type "01" appears exactly once, as the first line (file header)
    _assert_roundtrip(spec, lines[0], context="Group C line 1")


def test_nsf_record_counts_match_expected_claims_per_group(dataset_raw_dir, nsf_specs):
    """Cross-check against docs/DATASET_FINDINGS.md: one BA0 per claim,
    one claim per source image file."""
    expected_claims = {"Group A": 12, "Group B": 5, "Group D": 7}
    filenames = {
        "Group A": "DATAMATICS_UBH_HCFA_07212026 - Group A.txt",
        "Group B": "DATAMATICS_UBH_HCFA_07202026 - Group B.txt",
        "Group D": "DATAMATICS_UBH_HCFA_07212026 - Group D.txt",
    }
    for group, expected_count in expected_claims.items():
        lines = _read_lines(dataset_raw_dir / group / filenames[group])
        ba0_count = sum(1 for line in lines if line.startswith("BA0"))
        assert ba0_count == expected_count, group
