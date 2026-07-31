"""Runtime inference must not import or open evaluation answer sources."""

from __future__ import annotations

import ast
from pathlib import Path

RUNTIME_ROOTS = ("apps", "packages", "workers")
FORBIDDEN_IMPORTS = {
    "evaluation",
    "scripts.build_labels_from_fixed_width",
    "evaluation.build_dataset_labels",
}
FORBIDDEN_LITERALS = {
    "ground_truth.json",
    "all_claims_corrected.json",
    "offline_labels/labels.jsonl",
}


def test_runtime_has_no_evaluation_answer_dependency():
    violations: list[str] = []
    for root_name in RUNTIME_ROOTS:
        for path in Path(root_name).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                else:
                    modules = []
                if any(
                    module == forbidden or module.startswith(f"{forbidden}.")
                    for module in modules
                    for forbidden in FORBIDDEN_IMPORTS
                ):
                    violations.append(f"{path}: forbidden import {modules}")
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and any(value in node.value for value in FORBIDDEN_LITERALS)
                ):
                    violations.append(f"{path}: forbidden answer-source literal")
    assert not violations, "\n".join(violations)


def test_candidate_backfill_does_not_read_ground_truth():
    source = Path("evaluation/backfill_page_candidates.py").read_text(encoding="utf-8")
    assert "ground_truth" not in source
    assert "expected_raw" not in source
