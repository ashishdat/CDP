# STP Pipeline Architecture — field-cascade-v10 (DOB resolution)

## Why DOB redirects to HITL

On CMS-1500 box 3 the printed form draws **dashed vertical rules** between
MM | DD | YY. Whole-band OCR (paddle / rapid) frequently reads those rules as
digit **`1`**, so:

| Ink on form | Engine A | Engine B | Decision |
|-------------|----------|----------|----------|
| `01 / 08 / 18` | `11/08/2018` | `01/08/2018` | `CONFLICT_MARGIN_TOO_SMALL` → HITL |
| `01 / 09 / 60` | `01/19/1960` | `01/09/1960` | same |
| shaped date + header junk | `07/16/1946` | `MM DD …` | same (pre-v10) |

Secondary failure modes:

1. **Garbage wins ranking** — paddle emits `MM` / `9"i 24 i 07` with high raw
   confidence; shaped rapid/tesseract dates lose before reconciler.
2. **Cells only on miss** (v9) — whole-band already “accepted” a shaped but
   separator-contaminated date, so cell OCR never ran.
3. **Handwriting / faint ink** — still honest HITL; no invented DOB.

## v10 alternate strategy (shipped)

1. **Cells-FIRST** (`scripts/ocr_from_geometry.py`): inset MM/DD/YY crops away
   from the dashed rules, digit-whitelist tesseract + paddle/rapid, assemble
   only calendar-valid spans. Prefer `0X` over `1X` twins inside a cell.
2. **Separator-1 relief** (`prefer_dob_without_separator_one`): when two
   calendar-valid dates differ only by a leading `1` on MM or DD, prefer the
   clean copy — **even if confidence margin is large**.
3. **Calendar-valid group preference**: reconciler ranks DOB groups with a
   valid calendar date above header labels / digit blobs.
4. **Fragment relief**: calendar-valid top vs non-date junk → ACCEPT under
   `DATE_VALID` (not CONFLICT_MARGIN).

## Alternate tech stack (if residual handwriting remains)

| Option | Role | When |
|--------|------|------|
| **Current** paddle + rapid + tesseract digits | Production STP | Typed CMS, separator artifact |
| **TrOCR / Donut** (vision encoder-decoder) on DOB ROI | Handwriting | Residual after cells-first |
| **PaddleOCR-VL / PP-OCRv5 rec** fine-tuned on CMS DOB cells | Digit cells | High-volume typed forms |
| **Template inpainting** of vertical rules before OCR | Preprocess | When cells still bleed rule ink |
| **Human HITL** | Fail-closed | Ambiguous / empty / dual calendar conflict that is not separator-1 |

Do **not** invent DOBs or soften E3/identity to chase STP. Residual true
ambiguity stays Track-B HITL.

## Honesty

- True STP = `COMPLETED` ∧ ¬`review_required`
- Hackathon-1000 accuracy = `UNAVAILABLE_NO_GROUND_TRUTH` unless agent visual GT
- Separator peel only when both readings are calendar-valid and differ by that artifact
