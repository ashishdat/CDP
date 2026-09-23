# Latency tune after v13b (→ Independent-100 v13c)

**Problem:** Independent-100 median rose **33.3s → 39.0s** after accuracy-first LLM.

**Driver:** `force_cloud_despite_budget` treated every mono-engine `insured_name` as must-call Claude, wiping **39** `DOC_BUDGET_SKIP_CLOUD` skips (VLM name crops 61 → 99). Conflict agent also re-fired after every charge vision corroboration.

**Fix (precision-safe):**
1. `name_force_despite_budget` — override budget only for genuine name conflict / named unread gap; mono-engine E2 stays soft-optional.
2. Name residual attach uses `name_budget_unsettled` so soft/hard can skip optional name vision.
3. Charge conflict agent only when `field_needs_conflict_agent` (twin rivals); stop `force_vision` double-Claude.
4. Pass real DI agree state into `charge_accuracy_needs_vision` (no `di_ready=False` reset).

**Keep:** DI default ON for 0-line / place-shift charge; ID short-pad force; HITL-10 L1–L5 unlocks.

**Retest:** `evaluation_results/hackathon_100_independent_v13c` (offset 50, limit 100). Target: median ≤35s, True STP ≥90% (hold v13b floor).
