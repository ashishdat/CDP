"""Phase 1 orchestration may depend only on itself and the standard library."""

import ast
import subprocess
import sys
from pathlib import Path


def test_foundation_has_no_engine_business_or_benchmark_dependencies():
    root = Path(__file__).resolve().parents[2] / "packages" / "extraction_pipeline"
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    assert node.level == 1, path
                    continue
                modules = [node.module or ""]
            else:
                continue
            assert all(module.split(".")[0] in sys.stdlib_module_names for module in modules), path


def test_package_imports_without_installed_third_party_dependencies():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-S", "-c", "import packages.extraction_pipeline"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
