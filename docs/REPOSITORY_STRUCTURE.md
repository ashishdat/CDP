# Repository structure and ownership

The repository is a single Python distribution with independently deployable
applications and workers. Code belongs in the narrowest stable layer that can
own it.

| Directory | Responsibility | May depend on |
|---|---|---|
| `packages/` | Domain contracts and reusable infrastructure | `packages/` and third-party libraries |
| `apps/` | HTTP/API composition roots | `packages/` and app-local modules |
| `workers/` | Asynchronous processing and model adapters | `packages/`, worker-local modules, and the documented shared persistence bridge |
| `evaluation/` | Offline benchmarks, diagnostics, labeling and reports | All runtime layers; never imported by runtime code |
| `config/` | Versioned policy, template, model and output specifications | No executable code |
| `scripts/` | Repository maintenance and operator utilities | Standard library or installed project |
| `tests/` | Unit, architecture, integration, golden and performance tests | Any layer under test |
| `deploy/` | Docker, Compose, Helm, KEDA and monitoring assets | Versioned runtime entry points |

## Dependency direction

`packages` is the stable base. Applications and workers compose it. Evaluation
code observes runtime behavior but must never become an inference dependency.
The architecture check enforces these rules:

```text
evaluation ────────> apps / workers / packages
apps ───────────────────────────────> packages
workers ────────────────────────────> packages
packages ───────────────────────────> standard library / dependencies
```

The current worker consumers use `apps.ingestion_api.db` as a documented
persistence bridge. New cross-service persistence code must move into a shared
package instead of expanding that exception.

## Generated and private data

The following remain local and must never be committed:

- `.env*` files except the redacted root `.env.example`;
- `dataset_raw/`, `evaluation_data/`, and `evaluation_results/`;
- model caches, virtual environments, reports, and test scratch directories;
- reviewer crops, OCR payloads, and any artifact containing PHI.

Use `python scripts/clean_workspace.py` for safe cleanup. It removes only
reproducible caches and test scratch directories; it does not remove datasets,
evaluation results, model caches, or Docker volumes.

## Required quality gate

Before merging or deploying:

```bash
python scripts/check_architecture.py
ruff check apps packages workers evaluation scripts tests
pytest tests/unit tests/architecture -q
```

`make quality` runs the same local gate. GitHub Actions runs it on pushes and
pull requests.
