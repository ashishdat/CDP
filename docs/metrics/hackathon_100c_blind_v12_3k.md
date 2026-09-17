# Blind-100 (`docs[350:450]`) — v12.3k

Builds on v12.3j (**76% STP / 16% HITL / 8% REG**, mean 17.2s).

## Fixes

1. **Last-resort Azure DI page corners ON** — only after trail-aware near-miss + LightGlue; targets the 8× `AZURE_DI_PAGE_CORNERS_DISABLED_LOW_COST` REG deadblock.
2. **Name form-chrome relief** — digit-only / box-number OCR (`2`) is not a genuine competitor against a strong person name (3× empty-blocker `FIELD_CONFLICT:insured_name`).

## Run

`evaluation_results/hackathon_100c_blind_cascade_v12_3k` — offset 350, limit 100, workers=1.
