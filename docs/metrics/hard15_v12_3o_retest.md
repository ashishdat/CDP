# Hard-15 retest (v12.3o charge corroboration)

Freeze: `evaluation_data/hard15_v12_3o/`  
Cascade: `evaluation_results/hard15_v12_3o_cascade/`  
GT score: `evaluation_results/hard15_v12_3o_gt_score/summary.json`

## Gate vs result

| Must hold | Target | Result | Status |
| --- | ---: | ---: | --- |
| `false_accepts` | ≤ 1 | **2** | Near — both are `insured_name` vs weak GT (`PIRSR`, `SAME`) |
| Charge exact | ≥ 6/9 | **2/9** | Open — values still wrong; DI box-28 unshaped / quota errors |
| TRUE_STP | ≥ 60% | **~0–27%** | Open — charge HITL after fail-closed gate |
| REG HITL | 0 | **1** | Azure DI page-corners **403 F0 quota** (env, not logic) |

Label agreement held at **36/46 (78.3%)**. Identity AUTO recovered: DOB **7/7**, ID **11/11**, patient_name **9/9** exact on labeled fields.

## What shipped

1. **LINE_TOTALS AUTO gated** on `LINE_TOTALS_CORROBORATED`:
   - box-28 / DI within tolerance or digit-drop twin, **or**
   - multi-line with **exact** dual-engine agreement on every line
2. **Single-line dual-engine alone is not enough** (hard-15 FAs: 222 vs 233, 200 vs 22, 131 vs 135).
3. Conflicting DI stays as a competitor → HITL (no silent override).
4. Azure DI meter path written: `evaluation_results/hard15_v12_3o_cascade/azure_di_meter.jsonl` (34 events).

## Charge triage after gate

| Outcome | Count | Notes |
| --- | ---: | --- |
| Exact AUTO | 2 | EJGE.021, EJG7.036 values (EJG7.036 later HITL under single-line DI rule) |
| Wrong → HITL (good FA) | 7 | Line-sum / digit inflate no longer false STP |
| Charge FA | **0** | Down from 3 on first retest pass |

Box-28 Azure DI: many `AZURE_DI_UNSHAPED` + some `RuntimeError` (quota). Without a shaped box-28 read, single-line totals cannot safely AUTO and cannot correct wrong line OCR → exact stays 2/9.

## Remaining open (ordered)

1. **Charge value recovery** — gpt-4o currency crop (or DI after quota) when box-28 empty/unshaped; target ≥6/9 exact.
2. **insured_name FA (2)** — SELF-twin / strong-name AUTO vs agent GT fragments (`SAME`, `PIRSR`); tighten twin accept or treat those GT rows as SILVER abstain.
3. **STP recovery** — follows (1); fail-closed charge HITL is correct until values improve.
4. **Azure DI F0 quota** — REG corners + charge crops blocked; need paid tier or skip corners when 403.

**Hold 500** until charge exact ≥6/9 and FA ≤1.
