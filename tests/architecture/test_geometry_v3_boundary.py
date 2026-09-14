import ast
import sys
from pathlib import Path


def test_geometry_has_only_pixel_numeric_and_pipeline_dependencies():
    root = Path(__file__).resolve().parents[2] / "packages/geometry"
    allowed = sys.stdlib_module_names | {"numpy", "cv2"}
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    assert node.level == 1
                    continue
                modules = [node.module or ""]
            else:
                continue
            assert all(
                module.split(".")[0] in allowed
                or module.startswith("packages.extraction_pipeline.")
                for module in modules
            ), path
