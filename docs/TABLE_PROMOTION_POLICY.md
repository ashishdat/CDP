# Table shadow promotion policy

Table extraction runs in shadow mode and cannot modify extraction-v2. Promotion
is disabled by default in `config/table_shadow_v2.yaml`.

A field-level promotion requires a signed, versioned manifest, complete
provenance, approved labels, successful validation, and every configured gate:
95% table recall, 98% structured numeric/code accuracy, 99% row/column
alignment, at most 0.5% blank false positives, zero critical false accepts,
positive incremental recovery, and no extraction-v2 regression.

Provider-wide promotion is prohibited. Promotion eligibility output is an audit
artifact; applying it to production is a separate controlled release. The
baseline router, reconciliation rules, candidates, and final values remain
frozen throughout shadow evaluation.
