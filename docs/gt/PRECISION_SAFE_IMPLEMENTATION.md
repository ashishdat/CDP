# Precision-safe locked-50 plan (Box 28 authority)

## Done
- False-accept audit of 30 critical FAs → `docs/gt/false_accept_audit.csv` + discrepancy ledger (16 LABEL_SOURCE_CONFLICT quarantines). Classes: LABEL_WRONG, MODEL_WRONG, SOURCE_AMBIGUOUS, NORMALIZATION_WRONG. No PACKAGE_MAPPING_WRONG in the 30 (QR payloads are NUCC form URLs only).
- Box 28 value-only geometry (caption excluded, y1=1875) + tight crop ladder.
- Line-sum AUTO requires independent Box 28/DI corroboration (`BOX28_OR_DI_CORROBORATED`). Dual-engine / gpt+local alone → HITL.
- Box 2↔4 name and Box 3↔11a DOB redundancy (observed on DJJF.005).
- Quality lanes module (CLEAN_PRINTED / OVERPRINTED_DEGRADED / HANDWRITTEN).
- QR decode wired into package intelligence (family mapping; not member identity).
- Authorized member-index join (`CDP_AUTHORIZED_MEMBER_INDEX`) for Lane C — abstains without operator file. Example: `docs/reference/authorized_member_index.example.json`.
- Selective risk-coverage ledger scaffold — **no threshold fitting** until ≥600 adjudicated error-free accepts.

## Target
- Automate nine clean printed residuals: .015 .002 .005 .009 .019 .023 .024 .026 .027 → path to ~47/50 STP.
- Retain ≤3 HITL: .025 (overprinted), .034/.035 (handwritten) — resolve only via authorized structured join or grayscale original crops, not extra OCR guessing.

## Measurement
Locked 50 rerun: `evaluation_results/hackathon_50_box28_v3` (in progress). Do not tune thresholds on this run. Do not use the 300-claim diagnostic for fitting.
