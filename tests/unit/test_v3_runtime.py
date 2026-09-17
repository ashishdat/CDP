from copy import deepcopy
from itertools import product

import pytest

from packages_v3.runtime.adapter import LegacyAdapter
from packages_v3.runtime.dispatcher import RuntimeDispatcher
from packages_v3.runtime.feature_flags import RuntimeFlags
from packages_v3.runtime.models import STAGES


def setup_runtime(*, fail=None, differing=False, sink=None):
    calls, reports = [], []

    def operation(stage, implementation):
        def execute(value):
            calls.append((stage, implementation))
            if fail == stage and implementation == "v3":
                raise RuntimeError("shadow inference error")
            value[stage] = "different" if differing and implementation == "v3" else stage
            return value

        return execute

    legacy_stages = {name: operation(name, "legacy") for name in STAGES}

    def legacy(request):
        for operation in legacy_stages.values():
            operation(request)
        return request

    adapter = LegacyAdapter(
        legacy,
        legacy_stages=legacy_stages,
        v3_stages={name: operation(name, "v3") for name in STAGES[:3]},
        project=lambda stage, value: value[stage],
        legacy_snapshots=lambda value: deepcopy(value),
        shadow_safe=True,
    )
    return RuntimeDispatcher(adapter, sink=sink or reports.append), calls, reports


@pytest.mark.parametrize(
    "pipeline,shadow,geometry,ocr,ranking,validators", tuple(product((False, True), repeat=6))
)
def test_flag_matrix_and_response_authority(pipeline, shadow, geometry, ocr, ranking, validators):
    dispatcher, calls, reports = setup_runtime()
    flags = RuntimeFlags(pipeline, shadow, geometry, ocr, ranking, validators)
    request = {}
    result = dispatcher.execute(request, flags)
    assert result == {name: name for name in STAGES}
    if shadow or not pipeline:
        assert result is request
    else:
        assert result is not request
        assert request == {}
    expected_runs = 2 if shadow else 1
    assert len(calls) == len(STAGES) * expected_runs
    if shadow or pipeline:
        assert reports[0].coverage.coverage_percent == 100
        assert calls[-3:] == [(name, "legacy") for name in STAGES[3:]]
    if shadow:
        assert reports[0].comparison.response == "equal"
        assert all(status == "equal" for _, status in reports[0].comparison.stages)


def test_shadow_differences_do_not_replace_legacy_result():
    dispatcher, _, reports = setup_runtime(differing=True)
    request = {}
    result = dispatcher.execute(request, RuntimeFlags(pipeline_v3_shadow=True, geometry_v3=True))
    assert result is request
    assert result["geometry"] == "geometry"
    assert reports[0].comparison.response == "different"
    assert dict(reports[0].comparison.stages)["geometry"] == "different"


def test_shadow_failure_preserves_response_and_reports_incomplete_coverage():
    dispatcher, calls, reports = setup_runtime(fail="ocr")
    result = dispatcher.execute({}, RuntimeFlags(pipeline_v3_shadow=True, ocr_router_v3=True))
    assert result == {name: name for name in STAGES}
    assert reports[0].error_type == "RuntimeError"
    assert reports[0].coverage.stages[1].status == "failed"
    assert reports[0].coverage.stages[2].status == "skipped"
    assert calls.count(("ocr", "v3")) == 1


def test_active_v3_error_propagates_without_implicit_legacy_retry():
    dispatcher, calls, reports = setup_runtime(fail="ocr")
    with pytest.raises(RuntimeError):
        dispatcher.execute({}, RuntimeFlags(pipeline_v3=True, ocr_router_v3=True))
    assert calls == [("geometry", "legacy"), ("ocr", "v3")]
    assert reports[0].error_type == "RuntimeError"


def test_legacy_exception_identity_and_no_automatic_retry():
    dispatcher, calls, reports = setup_runtime()
    error = RuntimeError("original")

    def fail(request):
        raise error

    dispatcher.adapter.legacy = fail
    with pytest.raises(RuntimeError) as caught:
        dispatcher.execute({}, RuntimeFlags(pipeline_v3_shadow=True))
    assert caught.value is error
    assert calls == []
    assert reports[0].error_type == "RuntimeError"


def test_sink_and_projection_failures_do_not_affect_legacy_response():
    def fail(*args):
        raise RuntimeError("diagnostics down")

    dispatcher, _, _ = setup_runtime(sink=fail)
    dispatcher.adapter.project = fail
    dispatcher.adapter.legacy_snapshots = fail
    request = {}
    assert dispatcher.execute(request, RuntimeFlags(pipeline_v3_shadow=True)) is request


def test_clone_failure_does_not_prevent_legacy_execution():
    dispatcher, calls, reports = setup_runtime()

    def fail(request):
        raise TypeError("cannot clone")

    dispatcher.adapter.clone_request = fail
    assert dispatcher.execute({}, RuntimeFlags(pipeline_v3_shadow=True))
    assert len(calls) == 6
    assert reports[0].error_type == "TypeError"


def test_mutating_legacy_does_not_change_shadow_input():
    dispatcher, _, reports = setup_runtime()
    seen = []
    original = dispatcher.adapter.to_pipeline

    def prepare(request):
        seen.append(deepcopy(request))
        return original(request)

    dispatcher.adapter.to_pipeline = prepare
    dispatcher.execute({}, RuntimeFlags(pipeline_v3_shadow=True))
    assert seen == [{}]
    assert reports[0].comparison.response == "equal"


def test_timing_and_reports_are_per_request():
    dispatcher, _, reports = setup_runtime()
    ticks = iter(range(1000))
    dispatcher.clock = lambda: next(ticks)
    dispatcher.execute({}, RuntimeFlags(pipeline_v3_shadow=True), request_id="one")
    dispatcher.execute({}, RuntimeFlags(), request_id="two")
    assert reports[0].request_id == "one"
    assert reports[1].request_id == "two"
    assert reports[0].metrics.total_latency_ns > reports[0].metrics.legacy_latency_ns
    assert all(value > 0 for _, value in reports[0].metrics.stage_latency_ns)
    assert all(value == 0 for _, value in reports[1].metrics.stage_latency_ns)


def test_flags_default_off_and_parse_exact_environment_names():
    assert RuntimeFlags.from_mapping({}) == RuntimeFlags()
    flags = RuntimeFlags.from_mapping(
        {"FEATURE_PIPELINE_V3_SHADOW": "on", "FEATURE_VALIDATORS_V3": "1"}
    )
    assert flags.mode == "shadow" and flags.validators_v3
    with pytest.raises(ValueError):
        RuntimeFlags.from_mapping({"FEATURE_PIPELINE_V3": "maybe"})
    with pytest.raises(ValueError):
        RuntimeFlags(pipeline_v3="false")


def test_missing_enabled_component_is_a_failed_binding_not_fake_coverage():
    dispatcher, _, reports = setup_runtime()
    dispatcher.adapter.v3_stages.clear()
    dispatcher.execute({}, RuntimeFlags(pipeline_v3_shadow=True, geometry_v3=True))
    assert reports[0].coverage.stages[0].status == "failed"
    assert reports[0].coverage.coverage_percent == 0
