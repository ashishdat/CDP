# Independent-100 v13b — remaining 10 HITL attack plan

**Baseline:** 90/100 True STP (`docs/metrics/hackathon_100_independent_v13b.json`).  
**Goal:** clear safe subset → **95%** (need **+5**), then **96%** (+6).

All 10 are field-ink HITL; **9× `total_charge`**, **1× `patient_dob`**.

---

## Scenario taxonomy (from OCR + conflict-agent artifacts)

| # | Claim | Scenario | What happened | Safe unlock? |
|---|-------|----------|---------------|--------------|
| 1 | DJJM.040 | **Cents-column Box28 vs line** | Locals+DI=`251`, line=`2.51`; agent chose **LINES** but decision still shows `251` + `FINANCIAL_CONFLICT_HITL` | **Yes** — honor agent LINES value + E4 |
| 2 | DJKH.023 | **DI disagree after agent** | Agent=`70`, DI=`100`, paddle=`70`; `CHARGE_VISION_LOCAL` but `CONFLICT_MARGIN` | **Yes** — agent+local clears DI rival as soup |
| 3 | DJKH.030 | **Bleed / ×100 DI** | Agent=`251.43`, DI=`25143`; `BLEED_CENTS_FAIL_CLOSED` | **Yes** — cash ruling / Claude+local bleed relief |
| 4 | DJKH.040 | **Single-line vs Box28** | Line Σ path `157`; agent **BOX28**=`1571.63` (DI inflated `157163`) | **Maybe** — only if BOX28 corroborated without scale twin |
| 5 | DJKH.048 | **Hard rivals, agent abstain** | `701` vs DI `100`; agent **ABSTAIN** | **No** — keep HITL |
| 6 | DJKN.022 | **Single-line needs Box28** | Agent BOX28=`25` vs line=`450`; DI unshaped | **Maybe** — need line-cell vision + policy |
| 7 | DJKN.023 | **Implausible inflated** | Claude=`45000`, weak/empty locals, DI chrome | **No** — fail-closed correct |
| 8 | EJG7.005 | **Single-line vs Box28** | Agent BOX28=`400` vs line=`120`; DI=`400` | **Yes if** DI+Claude+policy treat as E4 and line is under-read |
| 9 | EJG7.007 | **DOB missing E2** | Charge already DI+local OK; DOB `1975-01-06` has `DATE_UNIQUE_CALENDAR` but `MISSING_E2` | **Yes** — calendar corroboration ⇒ E2 |
| 10 | EJG7.009 | **Digit-drop local scrap** | Agent+DI=`200`, paddle=`20`; still `MISSING_E4` | **Yes** — DI+Claude already agree; mint E4, scrap `20` |

**Conservative clear set (precision-safe): #1, #2, #3, #9, #10 → +5 → 95%.**  
**Stretch:** #8 (and maybe #4/#6 with stronger line vision) → 96%+.  
**Keep HITL:** #5, #7.

---

## Improvement levers (ordered)

### L1 — Honor conflict-agent financial resolution (unlocks #1, helps #4/#6/#8)
When `financial_conflict_agent` / `conflict_agent` resolves with `chosen` + `financial_side` in `{BOX28,LINES}`:
1. Set cascade/selected value to **chosen** (today DJJM.040 still surfaces `251` after LINES win).
2. Stamp authority reason `CONFLICT_AGENT_FINANCIAL_RESOLVED` / cents-column code into deterministic E4 path.
3. Do not leave `FINANCIAL_CONFLICT_HITL` if agent resolved.

### L2 — Post-agent E4 mint for vision+local / DI+Claude (unlocks #2, #10)
If conflict agent chooses amount **A** and ≥1 local **or** DI also has **A**, and remaining rivals are digit-drop / substring / scale soup:
- Mint `CHARGE_VISION_LOCAL_CONFIRMED` or `CHARGE_DI_LOCAL_CONFIRMED`.
- Clear `CONFLICT_MARGIN_TOO_SMALL` the same way DI-local soup relief does (without wiping true place-shift).

### L3 — Bleed cents + cash ruling (unlocks #3)
`251.43` with Claude agreement and DI `25143` (×100):
- Prefer cash-ruling / printed-cents path **without requiring `$`**.
- Treat DI ×100 as place-shift soup beside Claude+local `251.43`, not as a second total.
- Remove `BLEED_CENTS_FAIL_CLOSED` when cash ruling or Claude+local confirm printed cents.

### L4 — Single-line gate completion (helps #4, #6, #8)
`SINGLE_LINE_DUAL_ENGINE_NEEDS_BOX28` / `LINE_TOTALS_UNCORROBORATED`:
- After agent picks BOX28 **and** DI (or dual vision) corroborates same amount ±$1 → allow line-sum + box path to AUTO.
- If agent picks BOX28 but DI is scale-inflated twin only → HITL or prefer corroborated smaller amount.
- Always run line-cell Claude when sole line exists (already accuracy-first); feed into financial agent rivals.

### L5 — DOB calendar corroboration = E2 (unlocks #9)
`DATE_UNIQUE_CALENDAR_CORROBORATED` already present but `MISSING_E2` blocks STP:
- Map unique calendar corroboration (and/or Box3↔11a) into independent E2 for DOB policy.
- Do not require a second OCR family when calendar authority already fired.

### L6 — Explicit keep-HITL list
- **DJKH.048** agent abstain (701 vs 100).
- **DJKN.023** `45000` with empty/weak local + DI chrome.

---

## Expected STP if levers land

| After | Cleared claims | True STP |
|-------|----------------|----------|
| Now | — | **90%** |
| L1+L2+L3+L5 | ~5 | **~95%** |
| +L4 (EJG7.005 ± DJKH.040) | +1–2 | **~96–97%** |
| Irreducible | DJKH.048, DJKN.023 | remain HITL |

---

## Validation protocol
1. Unit tests per lever (agent value propagation, bleed relief, DOB E2 map, post-agent E4).
2. Redecide **only these 10** claims (`scripts/redecide_independent100_hitl.py` pattern).
3. If ≥5 flip with **zero** false accepts vs GT on flipped set → refresh Independent-100 or tip n100.
4. Stop if any place-shift / inflated AUTO appears on #5/#7 class.
