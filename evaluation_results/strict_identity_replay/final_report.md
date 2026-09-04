# Strict identity replay final report

- Assets: 1000
- Rendered pages: 2173
- Package count: 110
- Input manifest SHA-256: 2074fa83c63cd283afe55816ad95293be5d78340e75cadbde2352dc860d0e17f
- Cache hits: 40
- Cache hit rate: 0.018408
- Fresh OCR pages: 2133
- OCR failures: 0
- Retries: 0
- Workers: 6
- Wall-clock seconds: 9232.659527499985
- Effective pages/minute: 14.122
- Mean OCR runtime (ms): 27138.36275586756
- P50 OCR runtime (ms): 26894.906899993657
- P95 OCR runtime (ms): 51768.190199989476
- P99 OCR runtime (ms): 82586.693499994
- Peak memory: 2609.191 MB (OBSERVED_DURING_PARTIAL_REPLAY_WINDOW)
- Identity distribution: `{"CMS1500": 453, "NON_CLAIM": 0, "OTHER_CLAIM_FORM": 851, "SUPPORTING_DOCUMENT": 89, "UB04": 61, "UNKNOWN": 719}`
- CMS1500 localization calls: 453
- UB04 localization calls: 61
- OTHER_CLAIM_FORM localization calls: 0
- UNKNOWN localization calls: 0
- Family mismatch blocks: 0
- Conflicting identity evidence: 522
- Critical routing violations: 0
- Stale cache records rejected: 0
- False-UB04 canaries: `[{"canary": 1, "route": "OTHER_CLAIM_FORM", "ub04_localization_calls": 0, "ub04_rejected": true}, {"canary": 2, "route": "OTHER_CLAIM_FORM", "ub04_localization_calls": 0, "ub04_rejected": true}, {"canary": 3, "route": "OTHER_CLAIM_FORM", "ub04_localization_calls": 0, "ub04_rejected": true}]`
- Real-data classification accuracy: NOT_EVALUABLE_WITHOUT_TRUSTED_LABELS

OCR-bearing cache records remain local under evaluation_data and are not committed.
