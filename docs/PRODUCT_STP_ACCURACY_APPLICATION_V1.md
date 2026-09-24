# Product application design — 97% STP · 100% accepted accuracy

**Audience:** similar samples to Independent-1000 (CMS-1500, UB-04/freeform, mailroom separators).  
**Targets (going forward):**
- **Claim-page STP ≥ 97%** (REG separators excluded from denominator)
- **Accepted-field accuracy = 100%** (false accepts = 0 on every AUTO critical)

These are **product gates**, not aspirational dashboards. The app refuses to promote AUTO when evidence is incomplete; HITL is success for accuracy.

---

## 1. Metric contract (non-negotiable)

| Metric | Definition | Gate |
|---|---|---|
| **Claim-page STP** | `TRUE_STP / (n − REG_NO_CLAIM_INK)` | ≥ **0.97** |
| **All-page STP** | `TRUE_STP / n` | Reported only; REG floor ~15.9% on Independent-class mixes |
| **Accepted-field precision** | `(accepted_scored − FA) / accepted_scored` on **GOLD** GT after quarantine | **1.0** (FA = 0) |
| **Exact accuracy** | Exact match on scored fields (optional secondary) | ≥ 0.95 tip; not a substitute for FA=0 |

**Accuracy means:** every field we AUTO-accept is correct. We do **not** count abstentions (HITL/REG) as accuracy failures.

**FA scoring rules (product):**
1. Score **GOLD** agent GT only (SILVER echoes prior AUTO — circular).
2. Apply `docs/gt/ground_truth_discrepancy_ledger.json` quarantine.
3. Representation-only exact match (ISO dates, leading-zero IDs, optional middle initial, CMS `SAME` → patient).

Config: `config/product_stp_accuracy_contract_v1.yaml`  
Enforcer: `scripts/check_similar_sample_product_gate.py`

---

## 2. Application architecture (similar-sample path)

```
                    ┌─────────────────────────────────────┐
                    │  Similar-sample intake (page image) │
                    └─────────────────┬───────────────────┘
                                      │
                                      ▼
                    independent_case_router (page class)
                                      │
          ┌───────────────┬───────────┼────────────┬──────────────┐
          ▼               ▼           ▼            ▼              ▼
   MAILROOM_REG    CMS_GEOMETRY   UNSTRUCTURED   FIELD_INK    UNKNOWN
   keep REG        sift→OCR→      DI heuristics  residual     try CMS
   (not STP)       field_v13→     → promote      ladder       then DI
                   claim_decision
                                      │
                                      ▼
                         claim_decision + field_policy
                         + product accuracy_accept_policy
                         (blocks_stp, fail-closed)
                                      │
                                      ▼
                    ┌─────────────────────────────────────┐
                    │  Product gate (every batch / tip)   │
                    │  • claim_page_stp ≥ 0.97            │
                    │  • FA == 0 on GOLD accepted criticals│
                    │  • residual taxonomy published      │
                    └─────────────────────────────────────┘
```

Layers:

| Layer | Module |
|---|---|
| Case routing | `packages/extraction_recovery/independent_case_router.py` |
| Field residuals | `field_recovery_router` + `config/field_recovery_toolstack_v13.yaml` |
| Unstructured DI | `unstructured_reg_fallback.py` (+ accept-policy filter) |
| Claim STP | `packages/claim_decision/` (+ accept-policy demotion) |
| Accept policy | `packages/product_gates/accuracy_accept_policy.py` |
| Residual honesty | `packages/extraction_recovery/residual_taxonomy.py` |
| Accuracy / FA | `packages/evaluation/agent_gt_score.py` |
| Product gate | `packages/product_gates/similar_sample_gate.py` |

---

## 3. How we reach ≥97% STP on *similar* samples

Independent-1000 measured baseline is **96.2%** claim-page STP (809/841). Gap to 97% = **+7**. Going forward the app does **not** invent those 7; it:

1. **Classifies residuals** as `INK_ABSENT` | `POLICY_HOLD` | `REL_CONFLICT` | `RECOVERABLE`.
2. **Only AUTO-lifts `RECOVERABLE`** via dual corroboration (Box28↔lineΣ **or** DI agree **or** dual-engine).
3. **Keeps `REL_CONFLICT` / `INK_ABSENT` / `POLICY_HOLD` as HITL** (accuracy-preserving).
4. **Treats mailroom as REG**, never STP/HITL soup.

For *new* Independent-class batches with readable ink, the same router + toolstack + accept policy applies. Expected claim-page STP: **≥97%** once recoverable charge/DOB residuals clear under FA=0.

If a batch’s recoverable pool is empty, the gate reports **honest ceiling** and fails the 97% target rather than relaxing policy. Independent-1000 currently has **0 inventable recoverables** after taxonomy — residual HITL is policy hold / ink absent.

---

## 4. How we enforce 100% accepted accuracy

1. **Fail closed** at field reconciler / claim_decision (already).
2. **Product accuracy accept policy** demotes AUTO → HITL for:
   - placeholder OCR names (`LASTNAME`/`PNSTNANE`/…/`SPONSOR'S SSN`)
   - unresolved CMS `SAME` (must twin to patient first)
   - truncated Self insured name vs multi-token patient
   - form-label insured IDs
3. **No threshold fitting** on the evaluation corpus to buy STP.
4. **No spouse→patient twin** when relationship ≠ Self.
5. **Product gate FA=0**: GOLD criticals vs agent GT after quarantine; any FA → gate fail.
6. **Kill switches** stay on cloud residuals so a bad vision path cannot mint AUTO.

When GT is absent, the gate is **INCOMPLETE** (not a green pass). Production promotion still requires adjudicated holdout (`config/production_holdout_policy.yaml`).

---

## 5. Similar-sample profile

A page/batch is **Independent-class** when DI/family classification yields a mix of:

- `CMS1500` (geometry path)
- `UB04` / freeform (unstructured DI)
- `SEPARATOR` / fax / unique-id cover (REG)

Contract knobs: `config/product_stp_accuracy_contract_v1.yaml` → `similar_sample_profile`.

---

## 6. Operator loop (going forward)

```bash
# After any Independent-class cascade / HITL phase:
make product-gate
# or:
python3 -u scripts/check_similar_sample_product_gate.py \
  --ledger-a evaluation_results/hackathon_600_independent_v13c \
  --ledger-b evaluation_results/hackathon_400_remainder_independent_v13c \
  --write docs/metrics/similar_sample_product_gate_latest.json
```

Exit codes:
- `0` — claim STP ≥ 97% **and** FA = 0 (or GT incomplete allowed only with `--allow-incomplete-gt`)
- `1` — STP or FA gate failed
- `2` — config / ledger error

---

## 7. Explicit non-goals

- Absorbing REG into STP to inflate all-page rate.
- Declaring 100% “page accuracy” (STP+HITL+REG all correct labels) without adjudicated truth.
- Fitting calibrated confidence on Independent to clear residual HITL.
- Twin-promoting patient name onto Spouse/Other insured Box 4.
- Scoring SILVER agent GT as FA oracle (circular with prior AUTO).

---

## 8. Current measured baseline (Independent-1000)

| | Value |
|---|---|
| Claim-page STP | **96.20%** (809/841) — gate **FAIL** (<97%) |
| HITL | 32 (3.8% of claim pages) |
| REG | 159 (irreducible) |
| Gap to 97% | **+7** (no inventable recoverable ink on this tip) |
| Accepted FA (GOLD+quarantine) | **0** — precision **1.0** — gate **PASS** on accuracy |
| Residual taxonomy | POLICY_HOLD / INK_ABSENT dominant; RECOVERABLE ≈ 0 |

See `docs/metrics/similar_sample_product_gate_latest.json` and `docs/metrics/independent_hitl_program_results.json`.
