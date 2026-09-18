# Runtime dependency profiles

This repository **does not** support installing every model family into one
Python environment. Florence-2 pins `transformers==4.46.3` while GOT-OCR2
requires `transformers>=4.57,<5`. Those extras are **mutually exclusive**.

Use one runtime profile per image or venv.

## Install commands

From the repository root:

| Profile | Command |
| --- | --- |
| Core (API, workers shell, httpx/tenacity) | `pip install -r requirements/runtime-core.txt` |
| Handwriting (TrOCR-style) | `pip install -r requirements/runtime-handwriting.txt` |
| Florence-2 | `pip install -r requirements/runtime-florence.txt` |
| GOT-OCR2 | `pip install -r requirements/runtime-got-ocr2.txt` |
| Learned match (LightGlue) | `pip install -r requirements/runtime-learned-match.txt` |
| Cloud residual | `pip install -r requirements/runtime-cloud-residual.txt` |

Equivalent extras form (same exclusivity rules):

```bash
pip install -e ".[runtime-core]"
pip install -e ".[runtime-handwriting]"
pip install -e ".[runtime-florence]"      # not with runtime-got-ocr2
pip install -e ".[runtime-got-ocr2]"      # not with runtime-florence
pip install -e ".[runtime-learned-match]"
pip install -e ".[runtime-cloud-residual]"
```

### Development

```bash
pip install -e ".[dev]"
```

`dev` installs pytest/ruff/mypy only. It does **not** pull `florence` and
`got_ocr2` together (or either of them).

### Legacy extras

These remain available and must stay compatible with the rules above:

- `ocr`, `handwriting`, `learned-match`, `docling`, `ml`
- `florence` and `got_ocr2` — exclusive; never combine
- `ml` is `ocr` + `handwriting` only (no Florence / GOT)

### Cloud residual note

`runtime-cloud-residual` adds no packages beyond core today. Azure Document
Intelligence adapters rely on `httpx` and `tenacity`, which are already in the
base project dependencies.

## Verification

```bash
python scripts/check_dependency_profiles.py
python scripts/check_dependency_profiles.py --profile runtime-florence
python scripts/check_dependency_profiles.py --list
```

Exit codes are documented in `scripts/check_dependency_profiles.py`.
