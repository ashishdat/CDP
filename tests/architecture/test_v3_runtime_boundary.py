import ast
from pathlib import Path


def test_only_adapter_may_import_legacy_runtime_and_no_benchmark_imports():
    root = Path(__file__).resolve().parents[2] / "packages_v3/runtime"
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] if not node.level else []
            else:
                continue
            assert not any(
                name.startswith(("evaluation", "benchmark", "workers.retry")) for name in names
            )
            if path.name != "adapter.py":
                assert not any(
                    name.startswith(
                        ("workers", "apps", "packages.evidence_decision", "packages.claim_decision")
                    )
                    for name in names
                )
