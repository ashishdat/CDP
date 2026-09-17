"""The sole boundary allowed to bind legacy runtime services to V3 operations."""

from collections.abc import Callable, Mapping
from copy import deepcopy

from .models import STAGES


class LegacyAdapter:
    """Bind existing operations; no validators, decisions or evidence rules are copied.

    Shadow callbacks must be isolated in-memory computations. Persistence/event
    callbacks must remain outside this adapter. ``shadow_safe`` is an explicit
    composition assertion, not a sandbox for arbitrary supplied callbacks.
    """

    def __init__(
        self,
        legacy: Callable,
        *,
        legacy_stages: Mapping[str, Callable],
        v3_stages: Mapping[str, Callable],
        to_pipeline=deepcopy,
        from_pipeline=lambda value: value,
        project=lambda stage, value: value,
        legacy_snapshots=lambda value: {},
        clone_request=deepcopy,
        shadow_safe=False,
    ):
        unknown = (set(legacy_stages) | set(v3_stages)) - set(STAGES)
        if unknown:
            raise ValueError(f"Unknown runtime stages: {sorted(unknown)}")
        if set(v3_stages) - {"geometry", "ocr", "ranking"}:
            raise ValueError("Validators, decision and evidence must use legacy implementations")
        for operation in (*legacy_stages.values(), *v3_stages.values()):
            if not callable(operation):
                raise ValueError("Runtime operations must be callable")
        self.legacy = legacy
        self.legacy_stages = dict(legacy_stages)
        self.v3_stages = dict(v3_stages)
        self.to_pipeline = to_pipeline
        self.from_pipeline = from_pipeline
        self.project = project
        self.legacy_snapshots = legacy_snapshots
        self.clone_request = clone_request
        self.shadow_safe = shadow_safe

    def operation(self, stage, flags):
        enabled = {
            "geometry": flags.geometry_v3,
            "ocr": flags.ocr_router_v3,
            "ranking": flags.candidate_ranking_v3,
        }.get(stage, False)
        if enabled:
            if stage not in self.v3_stages:
                raise ValueError(f"Enabled V3 stage is not bound: {stage}")
            return self.v3_stages[stage], "v3", "FEATURE_ENABLED"
        operation = self.legacy_stages.get(stage)
        reason = (
            "LEGACY_IMPLEMENTATION"
            if operation is not None
            else "NOT_BOUND_AT_THIS_RUNTIME_BOUNDARY"
        )
        return operation, "legacy", reason

    @classmethod
    def for_claim(
        cls,
        legacy,
        *,
        geometry,
        ocr,
        ranking,
        geometry_request,
        ocr_request,
        ranking_candidates,
        merge_geometry,
        merge_ocr,
        merge_ranking,
        legacy_stages,
        to_pipeline,
        from_pipeline,
        project,
        legacy_snapshots,
        shadow_safe=False,
    ):
        """Bind all six stages without importing or reimplementing their algorithms.

        Builders translate current runtime data into the frozen V3 contracts.
        Mergers retain the request/claim aggregate between heterogeneous stages.
        Legacy callbacks must include the real validator, decision and evidence
        operations. Their existing order/dependencies belong to the callbacks.
        """
        if set(legacy_stages) != set(STAGES):
            raise ValueError("Full claim integration requires all six legacy stages")
        return cls(
            legacy,
            legacy_stages=legacy_stages,
            v3_stages={
                "geometry": lambda state: merge_geometry(
                    state, geometry.resolve(geometry_request(state))
                ),
                "ocr": lambda state: merge_ocr(state, ocr.route(ocr_request(state))),
                "ranking": lambda state: merge_ranking(
                    state, ranking.rank(ranking_candidates(state))
                ),
            },
            to_pipeline=to_pipeline,
            from_pipeline=from_pipeline,
            project=project,
            legacy_snapshots=legacy_snapshots,
            shadow_safe=shadow_safe,
        )
