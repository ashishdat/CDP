# Gap-close strategy (precision-safe)

Constraints (unchanged): no new OCR engine, no confidence-threshold fitting,
no inventing amounts. Prefer fail-closed HITL over a wrong AUTO.

## Gap taxonomy (from focus-12, locked-50, blind-150 partial)

| ID | Gap | Evidence | Close path |
|---|---|---|---|
| C1 | Units-bleed cents (`.07`/`.10`/`.22`/`.32`/`.43`) AUTO when `.00` sibling exists | DJKH.001 `157.07` vs GT `157.00`; DJKH.010/017/019/022 | Prefer same-dollar `.00`; BOX28↔line AUTO requires glyph-proven cents for non-`.00` |
| C2 | Dollars-ruling trailing digit (`70`→`701`) | DJKH.003/012 `701` vs GT `70` | Prefer full-window stem over ruling `+1` in `{1,4,5}` |
| C3 | Place-shift / digit soup | historical `4972`/`212400`/`400406` | Keep integrity DIGIT_SOUP + place-shift reject; never AUTO |
| C4 | Clipped Box 24F under-read | DJKH.002 line `[..1145]` → `157` vs GT `1571` | Cents-clip reject (done); repair from non-clipped candidates |
| C5 | Common-mode wrong agreement | DJJM.039 `251`≠`262`; DJJM.043 `370`≠`481` | Fail-closed unless glyph one-to-one on both paths; do not widen tolerance |
| C6 | Box28 deferred wipe loses alternate parse | DJJM.010/014 | Field-payload alternates + leading-contamination drop (done) |
| N1 | Box2≠Box4 non-Self name | DJJM.023 | Keep HITL (correct) |
| N2 | DOB residual | DJJM.019 | Existing DOB authority only; no threshold fit |
| N3 | Overprint / handwritten | .025/.034/.035 | Authorized member join only |

## Implementation order

1. **Charge total authority** — single resolver that, given Box 28 + line candidates, picks a safe amount or abstains (HITL).
2. **Wire before claim evidence** — so `CLAIM_TOTAL_CONFIRMED` and `BOX28_LINE_SUM_CORROBORATED` never bind bleed/ruling-tail soup.
3. **Tighten BOX28_LINE_SUM** — non-`.00` AUTO only with `GLYPH_ONE_TO_ONE` cents; otherwise HITL reason `BOX28_INTEGRITY_FAILED` / `LINE_SUM_INTEGRITY_FAILED`.
4. **Regression tests** for C1–C3 patterns + focus `.002`/`.010`/`.014` stay AUTO.
5. **Measure** on locked-50 / focus-12; do not fit thresholds.

## Explicit non-goals

- Do not AUTO `.023` by forcing Box2=Box4 under Child/Spouse.
- Do not treat SILVER GT near-miss dollars (`251` vs `262`) as a signal to widen corroboration tolerance.
- Do not resume blind-150 for fitting; resume only for measurement after guards land.

## Landed (this iteration)

| Guard | Where |
|---|---|
| C1 bleed cents → `.00` sibling | `charge_total_authority.resolve_safe_charge_total` |
| C1 non-`.00` Box28↔line AUTO needs glyph proof | `box28_line_sum_authority` predicate `bleed_cents_require_glyph_proof` |
| C2 ruling-tail only when longer is ruling-tagged | `resolve_safe_charge_total` (never `251→25`) |
| Untagged C2 abstain | `prefer_safe_charge_amount` |
| CLAIM_TOTAL bind exact confirmed (not ±$1) | `scripts/complete_from_extraction.py` |
| Wire before claim evidence | `complete_from_extraction.decide` |
