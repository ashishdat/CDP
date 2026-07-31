# Phase 1 — Dataset Inspection Findings

Source: `Images & Output.zip` (2.4 MB, 40 entries, no path traversal, no
executables — safe to extract). Extracted locally to `dataset_raw/`, which is
**git-ignored** and must never be committed: the sample claims contain
realistic-looking patient/provider PII/PHI (names, addresses, SSNs-shaped
IDs) and there is no way to confirm from the archive alone that it is
synthetic. All test fixtures checked into the repo are hand-built synthetic
look-alikes (`tests/golden/fixtures/`), never copies of this data.

## Archive layout

```
Images & Output.zip
├── UB92 File Specs - February 2012.doc      (OLE2, v510, Feb 2012)
├── NSF Matrix Version 2 15 - June 2013.doc  (OLE2, v002.15, June 2013)
├── Group A/
│   ├── DATAMATICS_UBH_HCFA_07212026 - Group A.txt   (reference output)
│   └── M047FJFL.001 .. .012                          (12 image files)
├── Group B/
│   ├── DATAMATICS_UBH_HCFA_07202026 - Group B.txt
│   └── M047IJAL.001-002, M047IJB0.001-003             (5 image files)
├── Group C/
│   ├── DATAMATICS_UBH_UB_07202026 - Group C.txt
│   └── M047IJBF.001 .. .006                           (6 image files)
└── Group D/
    ├── DATAMATICS_UBH_HCFA_07212026 - Group D.txt
    └── M047KJET.001 .. .007                           (7 image files)
```

Group A/B/C/D map directly to spec Bundles A/B/C/D.

## Image files: magic-byte / structural analysis

Every `.001`, `.002`, ... file — **regardless of extension** — is a TIFF:

- Magic bytes `49 49 2A 00` (`II*\0`) → little-endian (Intel) TIFF, confirmed
  by manually walking the IFD chain (no Pillow/libtiff assumptions).
- All images are **CCITT Group 4 / T.6** compressed (`Compression` tag = 4),
  bilevel (`PhotometricInterpretation` = 0, WhiteIsZero), ~1700×2200 px
  (≈200 DPI US-Letter).
- Multi-page files use a standard TIFF IFD chain (`next IFD offset` per page)
  — this is what Pillow calls `n_frames` / `im.seek(i)`. Verified end-to-end:
  `Image.open(...)`, `im.n_frames == 7` and correct per-page size for
  `Group B/M047IJB0.002`.

| Group | Files | Pages/file | Interpretation |
|---|---|---|---|
| A | 12 | all 1 page | Bundle A — single-page CMS-1500, one claim per file |
| B | 5 | 2, 2, 3, 7, 7 | Bundle B — multipage CMS-1500 + attachments, one claim per file |
| C | 6 | all 1 page | Bundle C — single-page UB claim form, one claim per file |
| D | 7 | 2, 2, 3, 9, 4, 4, 4 | Bundle D — multipage unstructured claim bundle, one claim per file |

**Numbered files are the unit of work**: each `.00N` file is one claim
document (single- or multi-page), not a loose page. This is confirmed by the
reference-output record counts below (N claim-header records == N image
files per group).

Because compression is exclusively Group-4, the decoder must use
Pillow/libtiff (bundles libtiff with G4 support on all platforms) rather
than a naive raster reader; `packages/storage/file_types.py` (magic-byte
sniff) is dependency-free, but the actual pixel decode
(`workers/document_preparation`) requires Pillow.

## Reference `.txt` outputs: fixed-width format analysis

All four `.txt` files are:
- Pure 7-bit ASCII (no bytes > 0x7F found).
- **CRLF** line endings, no BOM, no trailing blank line quirks.
- Fixed **record length per format** (see below), left-justified/blank-filled
  text fields and zero-padded numeric fields per the spec docs.

### Groups A, B, D → **NSF format** (National Standard Format, UnitedHealthcare
Matrix v002.15, June 2013), 320 bytes/record

Record types observed (2–3 char `RECORD ID` in cols 1-3):

| Record | Meaning | Cardinality |
|---|---|---|
| `AA0` | File header — submitter data | 1 per file |
| `BA0`/`BA1` | Batch header — provider data 1/2 | 1 per claim |
| `CA0` | Patient data | 1 per claim |
| `DA0` | Payer data 1 | 1–2 per claim (secondary payer repeats) |
| `DA2` | Payer data 3 | 1 per claim |
| `EA0` | Claim data | 1 per claim |
| `EK0` | Misc claim data (keyed claims) | Group D only, conditional |
| `FA0` | Claim root / service-line segment | 1 per service line (repeats) |
| `HA0` | Extra narrative | Groups B & D only (attachments/unstructured) |
| `XA0` | Claim trailer | 1 per claim |
| `YA0` | Batch trailer | 1 per claim |
| `ZA0` | File trailer | 1 per file |

Cross-check: Group A has 12 `BA0` records / 12 image files; Group B has 5 /
5; Group D has 7 / 7 — confirms **1 image file → 1 claim → 1 BA0..YA0
record group**. `HA0` (narrative) appears only for Groups B and D, which
matches the spec's Bundle B (attachments) and Bundle D (unstructured/needs
narrative capture) semantics — note Group D's *output* format is still
plain NSF/HCFA, i.e. Bundle D is about extraction flexibility (unknown
layout → configured schema / VLM), not a different output record format.

### Group C → **UB92 format** (UnitedHealthcare UB-92 File Specs v510, Feb 2012),
192 bytes/record

Record types observed (2-char code in cols 1-2):

| Record | Meaning | Cardinality |
|---|---|---|
| `01` | Processor data | 1 per file |
| `10` | Provider data | 1 per claim |
| `20` | Patient data | 1 per claim |
| `30`/`31` | Third-party payer data 1/2 | 2 per claim (repeats per payer) |
| `40` | Claim data (tan-occurrence) | 1 per claim |
| `46` | Additional provider information | 1 per claim |
| `60` | IP ancillary services (service lines) | 1+ per claim |
| `70` | Medical data (diagnosis/procedure) | 1 per claim |
| `80` | Physician data | 1 per claim |
| `90` | Claim control screen | 1 per claim |
| `95` | Provider batch control | 1 per claim |
| `99` | File control | 1 per file |

Cross-check: 6 `10` (provider) records == 6 image files == 6 claims.

### Spec documents

Both `.doc` files are legacy OLE2 binary Word docs (not OOXML) — converted
with `antiword` to plain text for parsing (`NSF_matrix.txt`,
`UB92_specs.txt`, git-ignored alongside the raw dataset). Each defines, per
record type, a field table with **No. / From / To / Picture (COBOL
PIC clause) / Required (R/C/O/N) / Description**. This is the source of
truth for `config/output_specs/nsf/*.yaml` and `config/output_specs/ub92/*.yaml`
(Phase 3) — JSON summaries are *not* sufficient per the spec, so the fixed-width
writer config schema mirrors these fields directly
(`record_type, field_name, start_position, length, alignment,
padding_character, data_type, format, required, default, source_field`).

## Implications for design

1. **Magic-byte detection is mandatory and sufficient** — extensions
   (`.001`, `.002`) carry no format information. `packages/storage/file_types.py`
   sniffs TIFF (II*/MM*), PDF (`%PDF`), PNG, JPEG from the first bytes only.
2. **Multipage decode must preserve every page as immutable original
   evidence** before any page is selected/discarded (Bundle B attachments
   must be *preserved*, not deleted).
3. **One NSF/UB92 claim record-group per source document** — the
   `Document` domain aggregate maps 1:1 to a `Claim` (Bundles A/B/C/D all
   observed this way in the sample set); multi-claim-per-file is not
   observed but the schema doesn't preclude it.
4. **Fixed-width output must be byte-exact**: fixed 320/192-byte records,
   CRLF terminators, ASCII only, exact justify/pad rules — golden tests
   compare output bytes, not just parsed field values.
