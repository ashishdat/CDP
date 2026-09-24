# Similar-sample 200 test report

**Source:** [Google Drive Hackathon zip](https://drive.google.com/file/d/1vhLhHwucY2gG6INZS3MB1MpAE1suaIJW/view?usp=sharing)  
**Selection:** stratified 200 across Groups A/B/C/D (135/37/17/11) — `selected_documents.txt`

## Speed fix

Live re-cascade with `--workers 2` + cloud/VLM/TrOCR/learned-matcher was ~**5 min/doc** (OCR flock contention under memory pressure + residual network/torch). Tip historical mean for the same docs was ~**27 s/doc**.

**Fix:** `scripts/run_similar_sample_200.py` defaults to a **FAST** profile (`workers=1`, cloud/VLM/TrOCR/matcher off, OCR lock off) and supports `--seed-tip` to reuse Independent tip DecisionResults in seconds.

**Smoke proof (3 docs, FAST):** mean **23.2 s/doc** (16.6 / 22.6 / 30.5) — ~12× faster than the stuck run.

```bash
python3 -u scripts/run_similar_sample_200.py --seed-tip   # seconds
python3 -u scripts/run_similar_sample_200.py              # fast live cascade
python3 -u scripts/run_similar_sample_200.py --full       # full product residuals
```

## Product gate (seeded tip ledger)

| Metric | Value | Target | Status |
|---|---|---|---|
| Claim-page STP | **97.56%** (160/164) | ≥ 97% | PASS |
| Accepted precision (GOLD) | **1.0** (FA=0) | 1.0 / FA=0 | PASS |
| HITL / REG | 4 / 36 | REG excluded from STP denom | |
| Gate | **PASS** | both bars | |

Residual HITL: `POLICY_HOLD: 4`

REG (36) are irreducible non-claim pages (15 DOCUMENT_SEPARATOR + 15 UNIQUE_ID_COVER + 6 FAX_PATCH), not failed claim forms.
