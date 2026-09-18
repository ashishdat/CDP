# Hold 500 — resolve 15-difficult over-HITL (v12.3o+)

## What the 15-difficult run showed

| Metric | Previous | New | Read |
| --- | ---: | ---: | --- |
| Label agreement | 69.6% | **78.3%** | Values improved |
| STP | 66.7% | **13.3%** | Disposition collapsed |
| HITL | 33.3% | **86.7%** | Over-review |
| Auto-accepted label disagreements | 13 | **1** | **Keep** — fewer false STP |
| Registration reviews | 4 | **0** | REG fixed |
| Technical failures | 0 | 0 | Stable |
| Charge exact vs labels | — | **2/9** | Primary accuracy hole |
| Labels | 46 across 11 docs | agent-created, not independent GT | Use for tuning only |

**Diagnosis:** Checks catch more wrong AUTOs (good) but leave too many *correct or near-correct* fields in REVIEW. Agreement↑ + STP↓ = classic **correct-but-reviewed** plus **charge still wrong/HITL**. Do **not** expand to 500 until STP recovers without raising false accepts above 1.

---

## Resolution strategy (ordered)

### Guardrail (every change)

Re-score the **same 15 docs / 46 labels**:

| Must hold | Target |
| --- | --- |
| `false_accepts` (AUTO ∧ ¬exact) | **≤ 1** |
| Charge exact on labeled charges | **≥ 6/9** before 500 |
| TRUE_STP on the 15 | **≥ 60%** (prior floor) without FA regression |
| REG HITL | stay **0** |

Reject any gate soften that lifts STP by raising false accepts.

---

### 1) Charge first — fix values, don’t waive disposition

**Why STP dies:** one critical `total_charge` HITL (or wrong AUTO now blocked) sinks the claim. 2/9 exact means most labeled charges never reach safe AUTO.

**Do:**

1. On the 9 labeled charge docs, dump AUTO value vs GT vs candidates (paddle / rapid / DI / line-sum).
2. Classify misses: digit-drop residual · wrong line count · both engines agree wrong · empty box-28 · DI garbage override.
3. Fixes (fail-closed):
   - Keep dual-engine digit-drop verify + `CDP_AZURE_DI_CHARGE_RESIDUAL=1`.
   - Prefer box-28 DI only when currency-shaped **and** within tolerance of line-sum **or** dual-engine twin; otherwise keep line-sum / HITL (don’t promote `179322`-class DI).
   - Require dual-engine **or** DI corroboration before single-line `LINE_TOTALS_RECONCILED` AUTO.
4. Re-score charge exact on the 9; stop when ≥6/9 and FA≤1.

**Don’t:** AUTO empty finance; soften E6 without corroboration.

---

### 2) Identity HITL — residual authority, not softer floors

**Why:** Identity checks drive HITL while agreement rose — many IDs/names/DOBs are closer to labels but still `CONFLICT_MARGIN` / calibration REVIEW.

**Do (preserve genuine twins HITL):**

| Field | Lever | Keep HITL when |
| --- | --- | --- |
| ID | Already shipped: `GPT4O_ID_WEAK_LOCAL_RELIEVED`, `GPT4O_ID_DIGIT_CONFLICT_TIEBREAK` | Two long shaped digit twins; gpt-4o third value |
| ID | Ensure hard-15 path actually attaches gpt-4o on weak/conflict (gate on) | — |
| Name | Prefer existing `NAME_*_RELIEVED` when engines agree after chrome strip | Unrelated tokens (`VITI`/`ILIA`) |
| DOB | DI punct + gpt-4o cell-split for abstain | Future DOB; distinct calendars |

**Don’t:** Globally soften 0.05 conflict margin or ID confidence floors (raises false STP — undoes 13→1).

---

### 3) Measurement split (avoid false confidence)

- **Label agreement** = value exact vs 46 agent labels (tuning signal only).
- **TRUE_STP** = all critical fields AUTO (ops signal).
- Publish both on every hard-15 retest; never treat agreement alone as ship gate.
- Add cost meter path per run (`CDP_AZURE_DI_METER_PATH` + gpt-4o usage) so 500 isn’t blind on $.

---

### 4) Gate to start 500

All of:

1. Hard-15 retest: STP ≥ 60%, HITL ≤ 40%, FA ≤ 1  
2. Charge exact ≥ 6/9 on labeled charges  
3. REG HITL = 0  
4. No new technical failures  
5. Cost meters writing for the retest  

Until then: **hold 500**.

---

## Immediate next engineering slice

1. Export the 15-doc IDs + 46 field labels from UI run history into a frozen list under `evaluation_data/hard15_*`.  
2. Run cascade + `score_hackathon_gt_accuracy` on that freeze.  
3. Charge miss triage → ship charge corroboration tighten.  
4. Confirm ID/name/DOB relief fires on remaining HITL blockers.  
5. Retest hard-15 against gate above → then 500.
