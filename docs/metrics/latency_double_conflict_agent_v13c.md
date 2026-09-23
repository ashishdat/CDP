# Latency: double conflict-agent Claude (v13c mid n300)

**Symptom:** Independent-300 wall clock drifted (last40 median **~43s** vs first40 **~35s**; n100 v13c was **37s**).

**Driver:** Charge twin rivals paid Claude **twice** — residual OCR path *and* end-of-OCR loop both called `maybe_attach_conflict_agent_to_field_row`. Last-60 telemetry: **26** fields with 2× `CONFLICT_AGENT_RESOLVED` on `total_charge` (~+10–15s/doc).

**Fix (precision-safe):**
1. Remove mid-residual conflict-agent call; keep single end-of-OCR pass after all candidates exist.
2. Make `maybe_attach_conflict_agent_to_field_row` **idempotent** (skip if `conflict_agent.attempted` / prior attempt engine present).

**Keep:** Financial BOX28↔LINES agent when sums disagree; DI / vision residuals; patient_name force-cloud; EJGE underread E4 unlocks.

**Ops:** Stopped n300 at 204/300 (SIGTERM); resumed with `--resume` on commit `1498589`.
