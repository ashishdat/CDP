from dataclasses import replace

import numpy as np
import pytest

from packages.extraction_pipeline import (
    ExtractionPipeline,
    FeatureFlag,
    FeatureFlags,
    PipelineContext,
    StageRegistry,
)
from packages.geometry import Box, GeometryEngine, GeometryRequest


def request():
    image = np.full((40, 40), 255, np.uint8)
    image[13:18, 14:20] = 0
    points = ((0, 0), (30, 0), (0, 30))
    return GeometryRequest(image, points, points, Box(10, 10, 25, 25), Box(5, 5, 30, 30))


@pytest.mark.parametrize(
    "pipeline_enabled,geometry_enabled",
    [(False, False), (False, True), (True, False), (True, True)],
)
def test_engine_is_only_invoked_with_both_flags(pipeline_enabled, geometry_enabled):
    calls = []
    sentinel = object()

    def legacy(payload, context):
        calls.append(payload)
        return sentinel

    engine = GeometryEngine()
    pipeline = ExtractionPipeline(StageRegistry((engine.stage(legacy),)), legacy)
    flags = set()
    if pipeline_enabled:
        flags.add(FeatureFlag.PIPELINE_V3)
    if geometry_enabled:
        flags.add(FeatureFlag.GEOMETRY_V3)
    payload = request()
    result = pipeline.run(payload, PipelineContext("geometry-test", FeatureFlags(flags)))
    if pipeline_enabled and geometry_enabled:
        assert not calls
        assert result.value.text_envelope == Box(14, 13, 20, 18)
        assert result.value.refined_roi == Box(12, 11, 22, 20)
    else:
        assert result.value is sentinel
        assert calls == [payload]


def test_repeated_resolution_is_deterministic_and_does_not_mutate_source():
    payload = request()
    before = payload.image.copy()
    engine = GeometryEngine()
    first = engine.resolve(payload)
    assert all(engine.resolve(payload) == first for _ in range(10))
    np.testing.assert_array_equal(payload.image, before)


def test_rejected_registration_does_not_emit_a_crop():
    result = GeometryEngine().resolve(replace(request(), source_points=()))
    assert result.refined_roi is None
    assert result.aligned_roi is None
    assert not result.registration.accepted


def test_out_of_cell_registration_does_not_clip_a_field_into_another_cell():
    result = GeometryEngine().resolve(replace(request(), source_cell=Box(20, 20, 30, 30)))
    assert result.refined_roi is None
    assert result.reasons == ("REGISTERED_ROI_OUTSIDE_SAFE_CELL",)


def test_engine_local_alignment_and_empty_source():
    payload = request()
    patch = payload.image[10:25, 10:25].copy()
    result = GeometryEngine().resolve(replace(payload, reference_patch=patch))
    assert result.alignment.accepted
    assert result.text_envelope == Box(14, 13, 20, 18)
    blank = np.full_like(payload.image, 255)
    result = GeometryEngine().resolve(replace(payload, image=blank))
    assert result.reasons == ("NO_FOREGROUND",)
    assert result.refined_roi is None
