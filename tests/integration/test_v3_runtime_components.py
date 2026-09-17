from copy import deepcopy

import numpy as np
from PIL import Image

from packages.candidate_ranking import CandidateRankingService
from packages.extraction_recovery.contracts import CandidateObservation
from packages.geometry import Box, GeometryEngine, GeometryRequest
from packages.ocr_router import ENGINE_ORDER, OCRObservation, OCRRouter, OCRRouteRequest
from packages_v3.runtime.adapter import LegacyAdapter
from packages_v3.runtime.dispatcher import RuntimeDispatcher
from packages_v3.runtime.feature_flags import RuntimeFlags
from packages_v3.runtime.models import STAGES
from workers.page_detection.text_extraction import TextLine


def test_full_stage_binding_uses_frozen_v3_components_and_legacy_tail():
    image = np.full((20, 20), 255, np.uint8)
    image[5:10, 5:10] = 0
    points = ((0, 0), (19, 0), (0, 19))
    request = {"image": image}
    reports, calls = [], []

    def merge(name):
        def apply(state, output):
            state[name] = output
            return state

        return apply

    def tail(name):
        def execute(state):
            calls.append(name)
            state[name] = "legacy-" + name
            return state

        return execute

    def observed_candidates(state):
        selected = state["ocr"].selected
        return [
            CandidateObservation(
                candidate_id="observed-1",
                raw_text=selected.observation.lines[0].text,
                selected_text=selected.observation.lines[0].text,
                engine=selected.engine,
                preprocessing_profile="test",
                ocr_confidence=0.8,
                localization_confidence=1,
                semantic_confidence=0,
                deterministic_valid=False,
            )
        ]

    def recognize(payload):
        return OCRObservation((TextLine("Original OCR", *payload.bbox, 0.8),))

    router = OCRRouter(lambda _: True, factories={name: lambda: recognize for name in ENGINE_ORDER})
    legacy_stages = {name: tail(name) for name in STAGES}
    adapter = LegacyAdapter.for_claim(
        lambda value: {"legacy": True},
        geometry=GeometryEngine(),
        ocr=router,
        ranking=CandidateRankingService(),
        geometry_request=lambda state: GeometryRequest(
            state["image"], points, points, Box(0, 0, 20, 20), Box(0, 0, 20, 20)
        ),
        ocr_request=lambda state: OCRRouteRequest(Image.fromarray(state["image"]), (3, 3, 12, 12)),
        ranking_candidates=observed_candidates,
        merge_geometry=merge("geometry"),
        merge_ocr=merge("ocr"),
        merge_ranking=merge("ranking"),
        legacy_stages=legacy_stages,
        to_pipeline=deepcopy,
        from_pipeline=lambda state: state["ranking"],
        project=lambda name, state: state[name],
        legacy_snapshots=lambda value: {},
        shadow_safe=True,
    )
    result = RuntimeDispatcher(adapter, sink=reports.append).execute(
        request,
        RuntimeFlags(
            pipeline_v3=True,
            geometry_v3=True,
            ocr_router_v3=True,
            candidate_ranking_v3=True,
            validators_v3=True,
        ),
    )
    assert result.selected_candidate_id == "observed-1"
    assert result.selected_value == "Original OCR"
    assert calls == ["validators", "decision", "evidence"]
    assert reports[0].coverage.coverage_percent == 100
    assert set(request) == {"image"}
    assert reports[0].error_type is None
