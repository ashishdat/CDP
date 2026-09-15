# STP pipeline architecture v7

## Why stop the 1000-run and redesign

Stopped Hackathon-1000 mid-run after **74 claims**. Result was structurally
broken, not “OCR needs more crops”:

| Metric (n=74) | Value | Meaning |
|---|---|---|
| Registration OK | 50/74 (67.6%) | ~1/3 never reach field cascade |
| Completed | 50/74 | Geometry → OCR → complete finished |
| True STP | **0/50** | Every completed claim forced HITL |
| Critical blockers | dob/name/id/charge on **all 50** | Not residual ink — systemic gate |
| `MISSING_E3_REGISTRATION_EVIDENCE` | **250/250** critical field decisions | Decision policy starved of E3 |
| `HARD_VALIDATION_PASSED` | 227/250 | Values were often format-valid |

Re-completing 8 of those same ExtractionResults after the E3 plumbing fix:

| Metric | Before (v6 ops path) | After E3 source fix |
|---|---|---|
| True STP | 0/8 | **5/8** |
| E3 missing on criticals | 8/8 fields | **0/8** |
| Residual HITL | — | 1× empty DOB ink, 2× empty/invalid charge |

So the dominant STP killer was **evidence plumbing**, not crop ladders.

## Root-cause stack (ordered by impact)

1. **E3 not attached on ops path**  
   `complete_from_extraction` only read `document.json`. Ops `app.py` writes
   `registration_report.json` (+ GeometryResult). `document.json` is often
   absent (or pruned). Decision policy correctly demands E3 → universal HITL.

2. **Dishonest gap taxonomy**  
   Gap classes labeled `HANDWRITING_UNREADABLE` / `EMPTY_FINANCIAL_INK` while
   selected values like `THOMAS DARLENE` / `910.00` existed. Taxonomy ran on
   blockers without reason-codes, so plumbing failures looked like ink failures.

3. **Registration failure track (~32%)**  
   `low_inlier_ratio`, `unsafe_perspective_distortion`, etc. No alternate
   registration ladder in the ops 1000 path — claim dies before OCR.

4. **Real residual field gaps (after E3)**  
   Empty DOB cells / unreconciled charges. These are honest HITL and belong to
   field-cascade crop/post-miss work — not policy softening.

## Architecture principles (v7)

1. **Artifact contracts over incidental files** — every stage emits a typed
   artifact the next stage is allowed to consume. No silent optional JSON that
   decision depends on.
2. **Evidence before disposition** — STP is impossible without the evidence
   classes policy requires. Plumbing bugs are P0 vs crop tuning.
3. **Two HITL tracks** — (A) registration/geometry HITL, (B) field-ink HITL
   after evidence-complete decision. Never conflate them in metrics.
4. **Crop/OCR recovers ink only** — never invent DOB/amount; never waive C2/C3
   identity gates to chase STP.
5. **Honest taxonomy** — gap class reflects the *decision reason*, not merely
   “blocker present”.

## Pipeline (v7)

```
ZIP page
  → REGISTER (+ recovery ladder)           → RegistrationEvidence.json  [E3 source]
  → GEOMETRY (template ROI bind)           → GeometryResult.json
       embeds registration_ref + accepted + alignment_confidence
  → FIELD CASCADE (crop × engines × span)  → OCRCandidates.json
  → RANK → VALIDATE → ASSEMBLE             → ExtractionResult.json
       source_artifacts: {registration, geometry, ocr, ranking, validation}
  → COMPLETE / DECIDE                      → FinalClaim.json
       builds FieldEvidenceBundle with E3 from RegistrationEvidence+ROI
  → GAP TAXONOMY (post-decision)           → only content/ink residual gaps
```

### Stage contracts

| Stage | Required outputs | Failure class |
|---|---|---|
| Register | `registration_report.json` with `attempts[].acceptance.accepted` | `REGISTRATION_HITL` |
| Geometry | `GeometryResult.json` status=SUCCESS + field ROIs | `GEOMETRY_HITL` |
| Field cascade | per-field candidates + cascade trace | continues |
| Assemble | ExtractionResult with **all** source_artifact refs | hard fail |
| Complete | DecisionResult; E3 attached when registration accepted | hard fail if refs missing |
| Taxonomy | gap_class only if reason ≠ missing E3 plumbing | metrics only |

## Strategy document

`config/field_cascade_strategy.yaml` → **field-cascade-v7**

Adds explicit evidence stages ahead of crop ladders, and honesty rules that
forbid labeling plumbing misses as handwriting gaps.

## Implementation slices (in order)

1. **P0 — E3 source fix** (done): read `registration_report.json`
   (and geometry field registration) in `complete_from_extraction`.
2. **P0 — Honest gap taxonomy** (done): skip / reclassify when reason codes include
   `MISSING_E3_*`.
3. **P1 — Canonical RegistrationEvidence**: write one artifact from app.py;
   GeometryResult carries `registration_ref`.
4. **P1 — Registration recovery ladder** (done on ops path): one cause-specific
   enhance retry — `IMAGE_ENHANCEMENT` (poor-scan) or `ALTERNATIVE_REGISTRATION`
   (perspective/rotation gates, including mixed poor-scan+geometric). Same
   template only; no threshold softening. Probe:
   `evaluation_results/hackathon_1000_cascade_v6/registration_recovery_probe/`.
5. **P2 — Residual DOB/charge cascade** (done on Track-B): day-edge `YYYY MM`
   DOB token assembly, multi-band `dob_cells`, charge far-right crop + digit
   whitelist, service-line charge scorer tolerates OCR `:`/`?` in raw when span
   already yields currency. Track-B residual probe **3/3 true STP**:
   `evaluation_results/hackathon_1000_cascade_v6/track_b_residual_probe_v2b/`.

## Track-B residual probe (Group A DJJF.002 / .010 / .012)

| Claim | Prior | After ladder + DOB/charge | Notes |
|---|---|---|---|
| M048DJJF.002 | DOB HITL | **true STP** | digit-band `116 11946 07` → `07/16/1946` |
| M048DJJF.010 | registration fail / charge residual | **true STP** | registers; charge via line OCR |
| M048DJJF.012 | charge via lines (flaky) | **true STP** | `200?` raw kept after `:`/`?` allowlist |

Registration remain Track-A HITL when both primary and one enhance fail gates
(no invented templates / no softened inlier floors).

## Metrics rules going forward

Report separately:

- `registration_ok_rate`
- `evidence_complete_rate` (E3 present on criticals)
- `true_stp_rate` (completed ∧ ¬review)
- `field_ink_hitl_rate` (Track B only)
- `registration_hitl_rate` (Track A only)

Do **not** quote a single STP% from a run where `evidence_complete_rate≈0`.

## Partial Hackathon-1000 freeze

Artifacts: `evaluation_results/hackathon_1000_cascade_v6/`  
Partial summary: `evaluation_results/hackathon_1000_cascade_v6/partial_summary.json`  
E3 unlock probe: `evaluation_results/hackathon_1000_cascade_v6/e3_fix_recomplete.json`
