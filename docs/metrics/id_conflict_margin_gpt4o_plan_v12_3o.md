# ID conflict-margin after gpt-4o residual — analysis + fix plan (v12.3o)

Case study: `Group A/M048HJE5.016` from `hackathon_hitl_fix_smoke_v12_3o`.

## What happened

| Stage | Value | Notes |
| --- | --- | --- |
| Local cascade | `338977` | rapidocr; raw `Y0 338977`; `ID_SHAPED`; **len 6** |
| gpt-4o gate | fires | `id_local_needs_gpt4o`: accepted but `len(alnum) < 7` |
| gpt-4o residual | `33847173` | shaped, conf 0.95; cascade accept `GPT4O_CROP_RESIDUAL` |
| Ranking | prefers `338977` | scores 0.622 vs 0.614 (`RANKING_MARGIN_LOW`) |
| Decision | selects `33847173` | calibrated ~0.982 |
| Disposition | **HITL** | `CONFLICT_MARGIN_TOO_SMALL` vs rapid `338977` |

DOB is already fixed (`07/30/1977`). Sole blocker is member ID.

## Why existing ID relief does not fire

String algebra on canonical forms `33847173` vs `338977`:

- Shared prefix only `338`, then **diverge** (`47173` vs `977`)
- Not substring / digit-drop / prefix-bleed
- Not single-glyph confusable insertion/substitution
- `_member_id_is_length_fragment` requires longer ≥ **10** and Δlen ≥ 3 → **false** (8 vs 6)

So reconciler correctly treats them as a **genuine competing identity** under current rules — and HITLs because calibrated margin &lt; 0.05.

## Use-case class

**Weak-local ID → gpt-4o crop residual upgrades value → weak local twin blocks STP via conflict margin.**

The residual is doing its job (second look on short/chrome local). Reconcile then undoes the win by keeping the short local as a `genuine` competitor.

Adjacent ID HITL modes (hard-150, pre-gpt4o) are mostly different:

- short/format-weak singles (`20755`, `OSC768X5`) → calibration floor
- chrome / label bleed → invalid format / E4
- Not this conflict-margin pattern (appears once gpt-4o is authorized)

## Do **not** do

| Anti-pattern | Why |
| --- | --- |
| Blind “prefer longer ID” | Breaks documented genuine conflicts (`909293380` vs `909295500`) |
| Soften global 0.05 margin for all IDs | Raises false STP on real twin digit disagreements |
| Expand length-fragment to any 6-vs-8 | These are not truncations; different digit bodies |

## Recommended fixes (ordered)

### 1. Residual-authority conflict relief (primary)

In `packages/candidate_reconciliation/reconciler.py` ID `genuine` filter / relief path:

When **primary** is `azure_gpt4o_crop` (shaped + `FORMAT_VALID`) **and** a competitor is a **weak local** that would still trip `id_local_needs_gpt4o` (len &lt; 7, chrome, or alpha soup), **drop that competitor** from the genuine conflict set.

Emit reason: `GPT4O_ID_WEAK_LOCAL_RELIEVED`.

Still HITL when:

- two long (≥7) shaped IDs disagree, or
- competitor is also CLOUD_AI / DI / multi-engine, or
- gpt-4o value itself fails shape/chrome filters

Unit cases:

- `33847173` (gpt4o) vs `338977` (rapid) → ACCEPT + relief reason
- `909293380` vs `909295500` (both long local) → still `CONFLICT_MARGIN_TOO_SMALL`
- gpt4o chrome / unshaped → no relief

### 2. Align ranking with residual intent (secondary)

Ranking currently prefers the short rapid twin by a hair. Add a small ranking prior for `azure_gpt4o_crop` when the local cascade value was length/chrome-weak so winner ≈ decision selection. Avoids `RANKING_MARGIN_LOW` thrash and confusing evidence bundles.

### 3. Independence group bugfix (hygiene)

`independence_group("azure_gpt4o_crop")` matches `"azure" in name` → `AZURE_READ_FAMILY`, same bucket as DI Read. Map `gpt4o` / `openai` to `CLOUD_AI_FAMILY` so residual corroboration accounting stays honest.

### 4. Optional trust gate on residual (safety)

If gpt-4o and the weak prior share **no** digit prefix (≥3) and edit distance is high, keep HITL (`GPT4O_ID_PRIOR_DIVERGENCE`) instead of auto-accept. HJE5.016 shares `338` so would still clear under (1).

## Validation

1. Unit tests above in `tests/unit/cases/`
2. Re-smoke `Group A/M048HJE5.016` → expect TRUE_STP if crop truth ≈ `33847173`
3. Visual spot-check ID crop (bbox `[1030,363,1568,401]`) before trusting STP economics
4. Re-run prior 6-doc auth set — no regression on docs that already STP

## Status

**Implemented** on `feature/cdp-v3`:

- Reconciler relief + early prefer: `GPT4O_ID_WEAK_LOCAL_RELIEVED`
- Shared-prefix safety gate (≥3 digits)
- `independence_group("azure_gpt4o_crop")` → `CLOUD_AI_FAMILY`
- Ranking engine reliability `azure_gpt4o_crop: 0.88` + ID residual prior in `rank_from_ocr.py`
- Unit tests: `tests/unit/cases/test_gpt4o_id_weak_local_relief.py`
