# Latency tune after v13b (→ Independent-100 v13c)

**Problem:** Independent-100 median rose **33.3s → 39.0s** after accuracy-first LLM.

**Driver:** `force_cloud_despite_budget` treated every mono-engine `insured_name` as must-call Claude, wiping **39** `DOC_BUDGET_SKIP_CLOUD` skips (VLM name crops 61 → 99). Conflict agent also re-fired after every charge vision corroboration.

**Fix (precision-safe):**
1. `name_force_despite_budget` — override budget only for genuine name conflict / named unread gap on **insured_name**; mono-engine E2 stays soft-optional.
2. **`patient_name` always forces cloud when vision is needed** — budget-skip caused false HITL on garbled Box 2 OCR (DJJM.036).
3. Self-twin inject requires **soft name agreement** — Self checkbox alone must not inject divergent insured OCR as a patient rival (`CONFLICT_MARGIN`).
4. Soft-equivalent name families (fuller↔fragment) mint E2 so `NAME_CONFLICT_RELIEVED` is not left as `MISSING_E2` (DJJM.046).
5. Charge conflict agent only when `field_needs_conflict_agent` (twin rivals); pass real DI state into charge vision needs.

**Keep:** DI default ON for 0-line / place-shift charge; ID short-pad force; HITL-10 L1–L5 unlocks.

**Retest:** `evaluation_results/hackathon_100_independent_v13c` (offset 50, limit 100). Target: median ≤35s, True STP ≥90% (hold v13b floor); patient_name must not be a false fail class.
