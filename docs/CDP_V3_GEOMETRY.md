# Phase 2: Geometry Engine

`packages.geometry` provides a source-only geometry engine beside existing workers.
It does not perform OCR, read benchmark truth, classify documents, validate field
values, or authorize fixed-form extraction. Existing public APIs are unchanged.

## Coordinate contract

Inputs are nonempty uint8 grayscale arrays. `Box` uses integer source pixels with
exclusive right and bottom edges. Registration maps reference-template landmarks
to observed source landmarks through deterministic least-squares affine fitting.
Callers supply matched structural landmarks; this phase does not discover them.
At least three non-collinear correspondences are required. Reflections, singular
transforms, nonfinite coordinates and excessive residuals are rejected.

The caller supplies a source-coordinate cell boundary independently of the
reference ROI. A transformed ROI outside that cell is rejected. Local alignment
matches an optional source-scale reference patch within a bounded search in the
safe cell. Blank or insufficient matches produce no refined crop. An absent
patch skips local refinement explicitly. Connected components and their envelope
describe dark foreground, not recognized text. Blank regions return no envelope.
Padding cannot escape the safe cell. Pixel inputs are never modified.

This initial implementation supports affine registration, not perspective
homography or automatic landmark detection. Structural lines within a requested
ROI are foreground; callers must supply the correct field interior. Geometry
acceptance is not proof of document identity or field correctness.

## Pipeline integration

`GeometryEngine.stage(legacy)` returns a Phase 1 registration controlled by
`GEOMETRY_V3`. Both `PIPELINE_V3` and `GEOMETRY_V3` must be enabled for the engine
to execute. The legacy callable retains its arguments, result and failure
behavior when disabled. A geometry-stage request is a `GeometryRequest`; its
result is a `GeometryResult`. Composition must pass that result to the next
appropriate stage. Existing production worker composition is unchanged.

## Validation and rollback

Synthetic tests cover affine translation/scale/shear/rotation, invalid landmarks,
local translation, safe-cell isolation, foreground coordinates, blank regions,
repeatability, source immutability and all flag combinations. Architecture tests
enforce dependencies on pixel/numeric libraries and Phase 1 only.

Run the three `test_geometry_v3*` test modules under `tests/unit`,
`tests/integration` and `tests/architecture`, together with Phase 1 tests.
No document benchmark is required or claimed by this change.

Disable `GEOMETRY_V3` to use the paired legacy stage, or revert the Phase 2 commit.

Validation: 31 new geometry tests plus 37 foundation/boundary checks passed.
Existing geometry regressions: 10 passed, 1 dataset-dependent test skipped.
Ruff and compilation passed. No benchmark was run.
