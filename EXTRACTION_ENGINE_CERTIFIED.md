# Extraction Engine Certification

**Certification: FAIL**

Original ten-claim stratified sample continued without restarting claims or modifying historical telemetry.

| Metric | Count |
|---|---:|
| Documents | 10 |
| Completed with ExtractionResult | 0 |
| Failed | 9 |
| Incomplete (interrupted) | 1 |
| Finished attempts | 9 |
| Interrupted attempts | 1 |
| classification success | 9/10 |
| registration success | 3/10 |
| geometry success | 3/10 |
| ocr success | 0/10 |
| ranking success | 0/10 |
| validators success | 0/10 |
| extraction_result success | 0/10 |

## Per-claim stages

| Claim | Classification | Registration | Geometry | OCR | Ranking | Validators | ExtractionResult |
|---|---|---|---|---|---|---|---|
| Group A/M048DJJF.001 | SUCCESS | FAILED | SKIPPED | SKIPPED | SKIPPED | SKIPPED | NOT_GENERATED |
| Group A/M048EJH6.004 | SUCCESS | SUCCESS | SUCCESS | FAILED_BEFORE_PROVIDER_EXECUTION | SKIPPED | SKIPPED | NOT_GENERATED |
| Group A/M048HJHO.044 | SUCCESS | SUCCESS | SUCCESS | FAILED_BEFORE_PROVIDER_EXECUTION | SKIPPED | SKIPPED | NOT_GENERATED |
| Group A/M048JJJG.014 | SUCCESS | FAILED | SKIPPED | SKIPPED | SKIPPED | SKIPPED | NOT_GENERATED |
| Group B/M048DJJZ.001 | SUCCESS | SUCCESS | SUCCESS | FAILED_BEFORE_PROVIDER_EXECUTION | SKIPPED | SKIPPED | NOT_GENERATED |
| Group B/M048JJJM.029 | SUCCESS | FAILED | SKIPPED | SKIPPED | SKIPPED | SKIPPED | NOT_GENERATED |
| Group C/M048DJJR.001 | SUCCESS | UNAVAILABLE | SKIPPED | SKIPPED | SKIPPED | SKIPPED | NOT_GENERATED |
| Group C/M048JJIO.001 | SUCCESS | UNAVAILABLE | SKIPPED | SKIPPED | SKIPPED | SKIPPED | NOT_GENERATED |
| Group D/M048DJK5.001 | OUTPUT_SAVED_ROUTING_COMPLETION_UNKNOWN | UNRECORDED | UNRECORDED | NOT_EXECUTED | NOT_EXECUTED | NOT_EXECUTED | NOT_GENERATED |
| Group D/M048JJJO.001 | SUCCESS | UNAVAILABLE | SKIPPED | SKIPPED | SKIPPED | SKIPPED | NOT_GENERATED |

## Resume boundaries

- Preserved first eight attempts, including historical handoff failures
- Recorded claim nine as interrupted; no safe application checkpoint exists
- Executed only previously unstarted claim ten

Code, configuration, and all pre-existing artifacts were hash-checked unchanged. No retries, telemetry edits, benchmark, tuning, Decision, or Evidence execution.

The three historical Geometry-to-OCR handoff failures remain failures: applying the code fix did not retroactively repair their telemetry. Claim 9 has only classification artifacts and cannot be resumed safely without repeating unknown work. Claim 10 is the only newly executed claim.

[Detailed resumed report](runs/extraction-certification-01/resume-57220f9/certification_report.json).

Execution used the existing working tree, including pre-existing uncommitted changes. HEAD was `57220f9`; this is not clean-commit certification. The saved source hash inventory records execution provenance.

STOP. Review required.
