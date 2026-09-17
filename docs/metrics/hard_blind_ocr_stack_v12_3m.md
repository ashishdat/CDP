# Hard blind stack — OCR fit + geometry vs agent

Hard blind-30 (`docs[420:450]`): **70% STP / 13% HITL / 17% REG**, mean 21.8s.

## What the failures actually are

| Bucket | Example | Reality | Best tool |
| --- | --- | --- | --- |
| REG “geometry” | `HJHO.015` | **Not a CMS-1500** — freeform handwritten claim note, no grid | Azure DI page read + **field agent (gpt-4o text)** — **not** a geometry agent |
| REG geometry | `HJHO.020/.021` | Real CMS-1500, heavy noise/skew; DI corners OK, SIFT still unsafe | Keep local ladder + DI corners; do **not** invent warp with a VLM |
| DOB HITL | `HJHO.019/.022/.024` | Handwriting / empty cells; TrOCR+DI crop unshaped | Handwriting stack: TrOCR → Azure DI crop → gpt-4o **crop** residual |
| ID HITL | `HJHO.022/.024/.025` | Label bleed or handwriting soup | Value-band + Azure DI ID crop; reject label-only; agent crop last |

## Do we need a geometry agent?

**No — not as the primary fix.**

1. Freeform pages have **no template to align**. A vision agent that “fixes geometry” cannot create CMS-1500 ROIs that do not exist. The right call is **unstructured extraction** (DI text → shaped fields / gpt-4o JSON).
2. True CMS-1500 REG failures already exhausted SIFT, near-miss, LightGlue, DI corners. A gpt-4o corner hint was previously replaced by DI ink polygons for cost/reliability. Softening acceptance gates would raise false STP.
3. Where an agent **does** help: **field reading** after DI on freeform pages, and **crop-scoped** handwriting residuals on registered pages — not homography invention.

## Tech stack change (shipped)

1. `CDP_UNSTRUCTURED_REG_FALLBACK=1` — on `REGISTRATION_FAILED`, run Azure DI full-page read + heuristic shaping; fill gaps with gpt-4o **text** JSON (`CDP_UNSTRUCTURED_REG_AGENT=1`).
2. DOB span: strip OCR header garbles (`MIM`…); accept **YY MM DD** when first token `>12` (`74 03 12` → `03/12/1974`).
3. Keep crop OCR order for registered pages: Rapid/Paddle/Tesseract → TrOCR → Azure DI crop (accept when date-shaped).

## Expected effect

- Freeform REG (`.015`-class) → HITL/STP via unstructured path instead of terminal Track A.
- Skewed real CMS REG → still honest REG until better local geometry (agent not the lever).
- DOB/ID on registered pages → incremental via assembly + crop residuals (agent crop optional next).
