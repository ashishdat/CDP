# Candidate Ranking

One runtime module, `packages/candidate_ranking.py`, exposes
`CandidateRankingService` using the existing `CandidateObservation`,
`CandidateScoringPolicy`, `rank_candidates`, and `CandidateRankingResult`.
No scoring implementation, policy file, validator, or acceptance threshold changes.

The service takes a private policy snapshot at construction and consumes one
field's observed candidates. It returns the unchanged ranking contract: winner,
selected value, ordered winner/loser IDs, component breakdowns, policy version,
and reasons. OCR text and input candidates are neither rewritten nor filtered.
Ties retain descending candidate-ID order; invalid winners retain their review
reason. A ranking winner is not a business acceptance decision.

`stage(legacy)` integrates through the existing `PIPELINE_V3` flag. Its input is
an iterable of existing `CandidateObservation` objects, not an OCR router result.
Callers must supply candidate generation and validation signals; this module
does not invent missing signals or change production worker composition.
Disabling the pipeline invokes the configured legacy callable unchanged.

Tests compare full serialized results with the existing ranker for empty,
blank, invalid, tied, duplicate-ID and ordinary candidates. Additional checks
cover policy isolation, score clipping, concurrency, input preservation and
pipeline rollback. Duplicate IDs retain legacy behavior, including keyed
breakdown collisions; callers should provide unique evidence IDs.

No benchmark or document-accuracy improvement is claimed. Review this module
independently before wiring it into production. Roll back by reverting this
commit or disabling `PIPELINE_V3` in a composition that opts into the service.

Validation: 139 tests passed across ranking, existing extraction recovery,
prior pipeline/geometry/OCR phases and OCR adapter regressions. Ruff and
compilation passed. No benchmark was run.
