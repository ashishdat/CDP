import ast
from pathlib import Path


def test_router_has_no_truth_business_or_direct_model_imports():
    path = Path(__file__).resolve().parents[2] / "packages/ocr_router.py"
    allowed = {
        "collections.abc",
        "dataclasses",
        "threading",
        "time",
        "PIL",
        "packages.extraction_pipeline.models",
        "packages.extraction_pipeline.registry",
        "packages.ocr_contracts",
        "packages.ocr_runtime_lock",
    }
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            assert all(alias.name in allowed for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module in allowed
