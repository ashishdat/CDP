# Permanent fix — corpus binding + run profiles

**Problem this closes:** the same two bugs kept returning on every new Drive zip.

1. **APP_FAILURE flood** — `--zip` pointed at a new corpus while `dataset.yaml` / `app.py` still opened the 1000-claim archive → missing pages → `geometry_missing` in ~1s.
2. **Fake STP collapse** — sample runners defaulted to **FAST** (residuals off) or **tip-seed**, then we scored the product gate and treated HITL on charge/DOB/name as “arch failed again.”

---

## Architecture

```
 selected_documents.txt
           │
           ▼
 ┌─────────────────────┐     must be SAME file
 │  bind_corpus()      │◄──── dataset.yaml.root ═══ --zip
 │  packages/          │
 │  corpus_binding     │──── every selected doc ∈ zip
 └─────────┬───────────┘
           │ writes corpus_binding.json
           ▼
 ┌─────────────────────┐
 │  apply_profile_env  │  FAST | PRODUCT | TIP_SEED
 │  packages/          │  config/run_profiles_v1.yaml
 │  run_profiles       │
 └─────────┬───────────┘
           │ writes run_manifest.json
           ▼
     cascade / app.py
           │
           ▼
 ┌─────────────────────┐
 │ product gate        │  refuses FAST / missing manifest
 │ similar_sample_gate │  TIP_SEED only with --allow-tip-seed
 └─────────────────────┘
```

| Profile | Residuals | Gate eligible? | Use |
|---|---|---|---|
| **FAST** | off | **No** | latency smoke (~20–30s/doc) |
| **PRODUCT** | on | **Yes** | STP ≥ 97% / FA=0 proof |
| **TIP_SEED** | n/a (replay) | only with `--allow-tip-seed` | known Independent tip regression — **not** a new Drive corpus |

---

## Code map

| Piece | Path |
|---|---|
| Corpus bind | `packages/corpus_binding/binding.py` |
| Profiles | `packages/run_profiles/profiles.py` + `config/run_profiles_v1.yaml` |
| Cascade fail-fast | `scripts/run_hackathon_1000_cascade.py` (bind before workers) |
| 5000 sample runner | `scripts/run_hackathon5000_sample_200.py` (`--product`) |
| Similar-200 runner | `scripts/run_similar_sample_200.py` (`--product`) |
| Gate | `packages/product_gates/similar_sample_gate.py` + `scripts/check_similar_sample_product_gate.py` |
| Contract flag | `gates.require_product_profile` in `config/product_stp_accuracy_contract_v1.yaml` |

---

## Operator commands

```bash
# Latency only (will NOT pass product gate)
python3 -u scripts/run_hackathon5000_sample_200.py --fresh

# Product STP proof on Hackathon-5000 sample
python3 -u scripts/run_hackathon5000_sample_200.py --product --fresh

# Gate (refuses FAST ledger)
python3 -u scripts/check_similar_sample_product_gate.py \
  --ledger-a evaluation_results/hackathon5000_sample_200_v1 \
  --allow-incomplete-gt \
  --write docs/metrics/hackathon5000_sample_200_v1/product_gate.json
```

Artifacts every run must leave:

- `corpus_binding.json` — dataset_id, archive path, doc membership
- `run_manifest.json` — `profile: FAST|PRODUCT|TIP_SEED`

Without those, the product gate fails closed (`RUN_MANIFEST_MISSING`).
