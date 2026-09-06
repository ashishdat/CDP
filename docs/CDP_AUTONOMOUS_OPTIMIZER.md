# Autonomous CDP Optimization Harness

The harness is an evaluation control plane, not runtime acceptance authority. It profiles
unresolved fields by `source / quality band / field / failure reason / OCR engine`, ranks
cohorts by claim-unlock value, and evaluates only closed-world deterministic experiment types.

Every experiment is bound to the GitHub baseline SHA and immutable safety-policy digest.
Tier A is capped at 100 pages, Tier B at 500 pages, and Tier C uses the full qualification
cohort. Tiers cannot be skipped. A critical false accept, truth/cohort/denominator mismatch,
precision or accuracy regression, HITL increase, or latency/cost breach immediately fails the
candidate. A failed candidate is recorded as `REVERTED` and cannot advance.

Qualification writes a tamper-evident manifest with `runtime_activation: false`. Production
activation remains a separate, independently approved release action. Azure GPT-4o remains a
shadow/adjudication input and never authorizes OCR acceptance in this harness.

## Commands

```powershell
python -m evaluation.autonomous_optimizer freeze-baseline `
  --test-results evaluation_results/autonomous_optimizer/baseline_test_results.json

python -m evaluation.autonomous_optimizer profile `
  --rows path/to/governed_failure_rows.json
```

Checkpoints use canonical JSON, SHA-256 binding, atomic replacement, and reject stale baseline,
stale policy, modified state, repeated tiers, oversized cohorts, and out-of-order promotion.
