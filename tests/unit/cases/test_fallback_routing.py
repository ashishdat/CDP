from packages.fallback_routing import (
    FallbackAction,
    FallbackRequest,
    GovernedInferenceCache,
    route_fallback,
)


def request(**overrides) -> FallbackRequest:
    values = {
        "identity_key": "A-06|1|CMS1500||patient_first",
        "crop_sha256": "abc",
        "prompt_version": "crop-v3",
        "model_version": "gpt-4o-2024-11-20",
        "normalization_version": "names-v2",
        "validation_policy_version": "extraction-v2",
    }
    values.update(overrides)
    return FallbackRequest(**values)


def test_reference_is_checked_before_local_and_cache(tmp_path) -> None:
    cache = GovernedInferenceCache(tmp_path / "cache.json")
    cache.put(request(), {"value": "MATHEW", "automatically_acceptable": False})
    decision = route_fallback(
        request(),
        reference_keys={request().identity_key},
        local_evidence={"route_promoted": True},
        cache=cache,
    )
    assert decision.action == FallbackAction.REFERENCE_VERIFIED


def test_cache_is_bound_to_crop_and_policy_versions(tmp_path) -> None:
    cache = GovernedInferenceCache(tmp_path / "cache.json")
    cache.put(request(), {"value": "MATHEW", "automatically_acceptable": False})
    assert route_fallback(
        request(), reference_keys=set(), local_evidence=None, cache=cache
    ).action == FallbackAction.CACHED_CLOUD_EVIDENCE
    assert route_fallback(
        request(crop_sha256="changed"),
        reference_keys=set(),
        local_evidence=None,
        cache=cache,
    ).action == FallbackAction.CALL_CLOUD
    assert route_fallback(
        request(prompt_version="crop-v4"),
        reference_keys=set(),
        local_evidence=None,
        cache=cache,
    ).action == FallbackAction.CALL_CLOUD


def test_cached_review_evidence_does_not_gain_authority(tmp_path) -> None:
    path = tmp_path / "cache.json"
    cache = GovernedInferenceCache(path)
    cache.put(request(), {"value": "MATHEW", "candidate_authority": "REVIEW_ONLY"})
    reloaded = GovernedInferenceCache(path)
    decision = route_fallback(
        request(), reference_keys=set(), local_evidence=None, cache=reloaded
    )
    assert decision.action == FallbackAction.CACHED_CLOUD_EVIDENCE
    assert decision.automatically_acceptable is False
