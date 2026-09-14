from concurrent.futures import ThreadPoolExecutor
from itertools import permutations

import pytest

from packages.candidate_ranking import CandidateRankingService
from packages.extraction_recovery.contracts import CandidateObservation
from packages.extraction_recovery.ranking import CandidateScoringPolicy, rank_candidates


def candidate(name, **changes):
    values = {
        "candidate_id": name,
        "raw_text": " original OCR ",
        "selected_text": "selected",
        "normalized_value": "normalized",
        "engine": "rapidocr",
        "preprocessing_profile": "REGIONAL_DEFAULT",
        "ocr_confidence": 0.8,
        "localization_confidence": 0.8,
        "semantic_confidence": 0.8,
        "deterministic_valid": True,
    }
    values.update(changes)
    return CandidateObservation(**values)


@pytest.mark.parametrize(
    "candidates",
    [
        [],
        [candidate("one")],
        [candidate("a"), candidate("z")],
        [candidate("invalid", deterministic_valid=False)],
        [candidate("blank", raw_text="", selected_text="", normalized_value=None)],
        [candidate("fallback", normalized_value="")],
        [
            candidate("invalid", deterministic_valid=False, ocr_confidence=1),
            candidate("valid", ocr_confidence=0.5),
        ],
        [candidate("same", ocr_confidence=0.2), candidate("same", ocr_confidence=0.9)],
    ],
)
def test_exact_existing_result_contract_and_input_preservation(candidates):
    policy = CandidateScoringPolicy.load()
    before = [c.model_dump(mode="json") for c in candidates]
    identities = [id(c) for c in candidates]
    actual = CandidateRankingService(policy).rank(candidates)
    assert actual.model_dump(mode="json") == rank_candidates(candidates, policy).model_dump(
        mode="json"
    )
    assert [c.model_dump(mode="json") for c in candidates] == before
    assert [id(c) for c in candidates] == identities


def test_ties_use_existing_descending_id_order_for_all_input_permutations():
    service = CandidateRankingService()
    for items in permutations([candidate("a"), candidate("c"), candidate("b")]):
        result = service.rank(iter(items))
        assert result.selected_candidate_id == "c"
        assert result.ranked_candidate_ids == ("c", "b", "a")
        assert "RANKING_MARGIN_LOW" in result.reason_codes


def test_invalid_winner_retains_review_reason_without_becoming_an_accept():
    result = CandidateRankingService().rank([candidate("one", deterministic_valid=False)])
    assert "WINNER_REQUIRES_REVIEW_DETERMINISTIC_INVALID" in result.reason_codes


def test_policy_is_snapshotted_and_custom_clipping_is_unchanged():
    policy = CandidateScoringPolicy(version="custom", weights={"ocr": 2})
    service = CandidateRankingService(policy)
    policy.weights["ocr"] = -1
    policy.version = "changed"
    result = service.rank([candidate("one")])
    assert result.score == 1
    assert service.policy_version == result.ranking_version == "custom"


def test_result_mutation_does_not_contaminate_later_requests():
    service = CandidateRankingService()
    inputs = [candidate("one")]
    expected = service.rank(inputs).model_dump(mode="json")
    first = service.rank(inputs)
    first.score_breakdown["one"]["ocr"] = 0
    assert service.rank(inputs).model_dump(mode="json") == expected


def test_concurrent_requests_are_independent():
    service = CandidateRankingService()
    inputs = [[candidate(str(i))] for i in range(20)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(service.rank, inputs))
    assert [r.selected_candidate_id for r in results] == [str(i) for i in range(20)]


def test_policy_is_loaded_once(monkeypatch):
    calls = []
    policy = CandidateScoringPolicy(version="test", weights={"ocr": 1})

    def load():
        calls.append(1)
        return policy

    monkeypatch.setattr(CandidateScoringPolicy, "load", load)
    service = CandidateRankingService()
    service.rank([])
    service.rank([])
    assert calls == [1]
